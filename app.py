import os
import requests
import subprocess
import json
import platform # Para verificar o sistema operacional
import getpass # Alternativa para obter o usuário atual
# import pwd # Removido - Não funciona no Windows
import psutil # Para obter estatísticas do sistema
import threading
import pwd # Para obter nome de usuário (Linux) - Adicionado para permissões
import time
import shutil # Para verificar permissões de escrita
from datetime import datetime, timedelta, timezone
from functools import wraps # Para criar decorators
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session

# --- Configurações ---

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Chave secreta para flash messages

SITES_DATA_FILE = 'sites_data.json'
SYSTEM_LOG_FILE = 'system_stats_log.json' # Arquivo para logs de estatísticas
LOG_INTERVAL_5MIN = 300 # Segundos (5 minutos)
LOG_RETENTION_5MIN = timedelta(minutes=30)
LOG_RETENTION_30MIN = timedelta(hours=24)
LOG_RETENTION_24H = timedelta(days=7)
log_lock = threading.Lock() # Lock para acesso seguro ao arquivo de log
NGINX_SITES_AVAILABLE = '/etc/nginx/sites-available/'
NGINX_SITES_ENABLED = '/etc/nginx/sites-enabled/'
SYSTEMD_SERVICE_DIR = '/etc/systemd/system/'
USERS_DATA_FILE = 'users.json'

# --- Funções Auxiliares ---

# --- Funções de Autenticação e Usuários ---

def load_users():
    """Carrega os dados dos usuários do arquivo JSON."""
    if not os.path.exists(USERS_DATA_FILE):
        # Cria o arquivo com o usuário padrão se não existir
        default_users = [{"username": "cico", "password": "admin"}]
        save_users(default_users)
        return default_users
    try:
        with open(USERS_DATA_FILE, 'r') as f:
            users = json.load(f)
            # Garante que 'cico' existe (caso seja removido manualmente)
            if not any(u['username'] == 'cico' for u in users):
                users.append({"username": "cico", "password": "admin"}) # Adiciona se faltar
                save_users(users)
            return users
    except json.JSONDecodeError:
        flash("Erro: Arquivo de usuários (users.json) corrompido. Recriando com usuário padrão.", 'error')
        default_users = [{"username": "cico", "password": "admin"}]
        save_users(default_users)
        return default_users
    except Exception as e:
         flash(f"Erro inesperado ao carregar usuários: {e}", 'error')
         return [{"username": "cico", "password": "admin"}] # Fallback seguro

def save_users(users):
    """Salva os dados dos usuários no arquivo JSON."""
    try:
        with open(USERS_DATA_FILE, 'w') as f:
            # Garante que 'cico' está na lista antes de salvar
            if not any(u['username'] == 'cico' for u in users):
                 users.insert(0, {"username": "cico", "password": "admin"}) # Adiciona no início se faltar
            json.dump(users, f, indent=4)
    except Exception as e:
        flash(f"Erro crítico: Não foi possível salvar os dados dos usuários em {USERS_DATA_FILE}: {e}", 'error')

def verify_password(stored_password, provided_password):
    """Verifica a senha (atualmente comparação direta)."""
    # IMPORTANTE: Isso NÃO é seguro para produção! Senhas devem ser hasheadas.
    return stored_password == provided_password

# --- Decorators de Autenticação/Autorização ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash("Por favor, faça login para acessar esta página.", 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('username') != 'cico':
            flash("Você não tem permissão para acessar esta área.", 'error')
            return redirect(url_for('index')) # Redireciona para a página inicial
        return f(*args, **kwargs)
    return decorated_function

# --- Funções de Log de Estatísticas ---

def load_system_logs():
    """Carrega os logs de estatísticas do arquivo JSON."""
    with log_lock: # Garante acesso exclusivo ao arquivo
        if not os.path.exists(SYSTEM_LOG_FILE):
            return {'log_5min': [], 'log_30min': [], 'log_24h': []}
        try:
            with open(SYSTEM_LOG_FILE, 'r') as f:
                data = json.load(f)
                # Garante que as chaves existem
                if 'log_5min' not in data: data['log_5min'] = []
                if 'log_30min' not in data: data['log_30min'] = []
                if 'log_24h' not in data: data['log_24h'] = []
                return data
        except json.JSONDecodeError:
            print(f"Erro: Arquivo de log de estatísticas {SYSTEM_LOG_FILE} corrompido. Criando um novo.")
            return {'log_5min': [], 'log_30min': [], 'log_24h': []}
        except Exception as e:
            print(f"Erro inesperado ao carregar logs de estatísticas: {e}")
            return {'log_5min': [], 'log_30min': [], 'log_24h': []} # Retorna vazio em caso de erro

def save_system_logs(logs):
    """Salva os logs de estatísticas no arquivo JSON."""
    with log_lock: # Garante acesso exclusivo ao arquivo
        try:
            with open(SYSTEM_LOG_FILE, 'w') as f:
                json.dump(logs, f, indent=2) # Indentação menor para economizar espaço
        except Exception as e:
            print(f"Erro crítico: Não foi possível salvar os logs de estatísticas em {SYSTEM_LOG_FILE}: {e}")

def prune_logs(log_list, retention_period):
    """Remove entradas antigas de uma lista de logs."""
    if not log_list:
        return []
    now = datetime.now(timezone.utc)
    cutoff_time = now - retention_period
    # Converte strings ISO de volta para datetime para comparação
    return [
        entry for entry in log_list
        if datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00')) >= cutoff_time
    ]

def log_system_stats():
    """Coleta e salva as estatísticas do sistema."""
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        # Usar UTC para timestamps para evitar problemas com fuso horário e DST
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z') # Formato ISO 8601 UTC

        current_stats = {
            'timestamp': timestamp,
            'cpu_usage': cpu,
            'memory_usage': memory.percent,
            'disk_usage': disk.percent
        }

        logs = load_system_logs()
        now = datetime.now(timezone.utc)

        # --- Log de 5 minutos ---
        logs['log_5min'].append(current_stats)
        logs['log_5min'] = prune_logs(logs['log_5min'], LOG_RETENTION_5MIN)

        # --- Log de 30 minutos (Downsampling) ---
        # Adiciona um ponto a cada 30 minutos (aproximadamente)
        last_30min_log_time = None
        if logs['log_30min']:
            last_30min_log_time = datetime.fromisoformat(logs['log_30min'][-1]['timestamp'].replace('Z', '+00:00'))

        # Adiciona se for o primeiro log ou se passaram 30 minutos desde o último
        if not last_30min_log_time or (now - last_30min_log_time) >= timedelta(minutes=30):
            logs['log_30min'].append(current_stats)
            logs['log_30min'] = prune_logs(logs['log_30min'], LOG_RETENTION_30MIN)

        # --- Log de 24 horas (Downsampling) ---
        # Adiciona um ponto a cada 24 horas (aproximadamente)
        last_24h_log_time = None
        if logs['log_24h']:
            last_24h_log_time = datetime.fromisoformat(logs['log_24h'][-1]['timestamp'].replace('Z', '+00:00'))

        # Adiciona se for o primeiro log ou se passaram 24 horas desde o último
        if not last_24h_log_time or (now - last_24h_log_time) >= timedelta(hours=24):
            logs['log_24h'].append(current_stats)
            logs['log_24h'] = prune_logs(logs['log_24h'], LOG_RETENTION_24H)

        save_system_logs(logs)
        # print(f"[{datetime.now()}] Estatísticas logadas com sucesso.") # Debug

    except Exception as e:
        print(f"Erro ao coletar/logar estatísticas do sistema: {e}")

def set_directory_permissions(directory_path, username):
    """Define o dono do diretório para o usuário especificado (Linux apenas)."""
    if platform.system() != 'Linux':
        print("Skipping permission setting on non-Linux system.")
        return True # Considera sucesso em não-Linux

    if not os.path.exists(directory_path):
        flash(f"Erro interno: Diretório '{directory_path}' não encontrado para definir permissões.", "error")
        return False

    # Verifica se o usuário do sistema existe
    try:
        pwd.getpwnam(username)
    except KeyError:
        flash(f"Aviso: Usuário do sistema '{username}' não encontrado. Não foi possível definir permissões na pasta '{directory_path}'.", 'warning')
        return False # Falha pois o usuário não existe no OS

    print(f"Definindo permissões para {username} em {directory_path}")
    # -R para recursivo
    result = run_command(['sudo', 'chown', '-R', f'{username}:{username}', directory_path], check=False)
    if result and result.returncode == 0:
        # Opcional: Definir permissões mais específicas (ex: 755 para diretórios, 644 para arquivos)
        # run_command(['sudo', 'chmod', 'u+rwX,go+rX,go-w', directory_path], check=False) # Exemplo: drwxr-xr-x
        flash(f"Permissões definidas para o usuário '{username}' no diretório '{directory_path}'.", 'info')
        return True
    else:
        flash(f"Falha ao definir permissões para '{username}' em '{directory_path}'. Detalhes: {result.stderr if result else 'N/A'}", 'error')
        return False

def create_home_symlink(target_path, username, site_domain):
    """Cria um link simbólico na home do usuário apontando para o target_path (Linux apenas)."""
    if platform.system() != 'Linux':
        print("Skipping symlink creation on non-Linux system.")
        return True

    if not os.path.exists(target_path):
        flash(f"Erro interno: Diretório de destino '{target_path}' não encontrado para criar link simbólico.", "error")
        return False

    # Gera um nome seguro para o link a partir do domínio
    site_link_name = site_domain.replace('.', '-')

    # Obtém o diretório home do usuário
    try:
        user_info = pwd.getpwnam(username)
        home_dir = user_info.pw_dir
        user_uid = user_info.pw_uid
        user_gid = user_info.pw_gid
    except KeyError:
        flash(f"Aviso: Usuário do sistema '{username}' não encontrado. Não foi possível criar link simbólico na home.", 'warning')
        return False # Usuário não existe no OS

    symlink_path = os.path.join(home_dir, site_link_name)

    # Verifica se o link já existe
    if os.path.lexists(symlink_path): # Use lexists para detectar links quebrados também
        # Verifica se já aponta para o lugar certo
        if os.path.islink(symlink_path) and os.readlink(symlink_path) == target_path:
             print(f"Link simbólico '{symlink_path}' já existe e aponta corretamente.")
             return True
        else:
            flash(f"Aviso: Já existe um arquivo ou link inválido em '{symlink_path}'. Link simbólico não foi criado.", 'warning')
            return False # Impede a sobrescrita

    # Verifica se o diretório home existe e tem permissão de escrita para o usuário
    if not os.path.isdir(home_dir) or not os.access(home_dir, os.W_OK, effective_ids=True):
         # Tenta garantir que o dono do home é o próprio usuário (pode falhar se home for montado de forma estranha)
         run_command(['sudo', 'chown', f'{username}:{username}', home_dir], check=False)
         # Verifica de novo após tentar corrigir
         if not os.path.isdir(home_dir) or not os.access(home_dir, os.W_OK, effective_ids=True):
             # Tenta criar como root e mudar dono (menos ideal)
             print(f"Aviso: Diretório home '{home_dir}' inacessível ou sem permissão de escrita para {username}. Tentando criar link como root e ajustar dono.")
             result_ln = run_command(['sudo', 'ln', '-s', target_path, symlink_path], check=False)
             if result_ln and result_ln.returncode == 0:
                result_chown = run_command(['sudo', 'chown', '-h', f'{username}:{username}', symlink_path], check=False) # -h para não seguir o link
                if result_chown and result_chown.returncode == 0:
                     flash(f"Link simbólico criado em '{symlink_path}' (como root e dono ajustado).", 'info')
                     return True
                else:
                    flash(f"Falha ao ajustar dono do link simbólico '{symlink_path}' após criação.", 'error')
                    run_command(['sudo', 'rm', symlink_path], check=False) # Tenta limpar
                    return False
             else:
                flash(f"Falha ao criar link simbólico '{symlink_path}' (mesmo como root).", 'error')
                return False


    print(f"Criando link simbólico em {symlink_path} para {target_path} como usuário {username}")
    # Tenta criar o link como o próprio usuário usando sudo -u
    # Isso garante que o link pertença ao usuário correto desde o início
    result = run_command(['sudo', '-u', username, 'ln', '-s', target_path, symlink_path], check=False)

    if result and result.returncode == 0:
        flash(f"Link simbólico criado com sucesso em '{symlink_path}'.", 'success')
        return True
    else:
        flash(f"Falha ao criar link simbólico em '{symlink_path}'. Detalhes: {result.stderr if result else 'N/A'}", 'error')
        # Tenta verificar se o diretório home tem permissão de escrita para o usuário
        if not os.access(home_dir, os.W_OK):
             flash(f"Verifique as permissões de escrita no diretório home: {home_dir}", "warning")
        return False


def run_logging_scheduler():
    """Executa o log de estatísticas periodicamente em uma thread."""
    print("Iniciando scheduler de log de estatísticas...")
    while True:
        log_system_stats()
        # Espera o intervalo definido (com pequena correção para drift, embora simples)
        time.sleep(LOG_INTERVAL_5MIN)


# --- Funções Auxiliares Nginx/Systemd ---

def run_command(command, check=True, shell=False):
    """Executa um comando no shell e retorna o resultado."""
    print(f"Executando comando: {' '.join(command)}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=check, shell=shell)
        print("Saída:", result.stdout)
        if result.stderr:
            print("Erro:", result.stderr)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Erro ao executar comando: {e}")
        print("Saída de erro:", e.stderr)
        flash(f"Erro ao executar comando: {' '.join(command)}. Detalhes: {e.stderr}", 'error')
        return None
    except Exception as e:
        print(f"Erro inesperado ao executar comando: {e}")
        flash(f"Erro inesperado: {e}", 'error')
        return None

def load_sites():
    """Carrega os dados dos sites do arquivo JSON."""
    if not os.path.exists(SITES_DATA_FILE):
        return []
    try:
        with open(SITES_DATA_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        flash("Erro ao ler o arquivo de dados dos sites (JSON inválido).", 'error')
        return [] # Retorna lista vazia em caso de erro de leitura
    except Exception as e:
         flash(f"Erro inesperado ao carregar sites: {e}", 'error')
         return []


def save_sites(sites):
    """Salva os dados dos sites no arquivo JSON."""
    try:
        with open(SITES_DATA_FILE, 'w') as f:
            json.dump(sites, f, indent=4)
    except Exception as e:
        flash(f"Erro crítico: Não foi possível salvar os dados dos sites em {SITES_DATA_FILE}: {e}", 'error')


def generate_nginx_config(template_name, domain, **kwargs):
    """Gera a configuração do Nginx a partir de um template."""
    try:
        with open(os.path.join('nginx_templates', template_name), 'r') as f:
            template = f.read()

        config = template.replace('{{DOMAIN}}', domain)
        for key, value in kwargs.items():
            config = config.replace(f'{{{{{key.upper()}}}}}', str(value)) # Usa {{VAR}} no template

        config_path = os.path.join(NGINX_SITES_AVAILABLE, domain)
        with open(config_path, 'w') as f:
            f.write(config)
        return config_path
    except FileNotFoundError:
        flash(f"Erro: Template Nginx '{template_name}' não encontrado.", 'error')
        return None
    except Exception as e:
        flash(f"Erro ao gerar configuração Nginx para {domain}: {e}", 'error')
        return None

def enable_nginx_site(domain):
    """Cria o link simbólico para habilitar o site no Nginx."""
    config_path = os.path.join(NGINX_SITES_AVAILABLE, domain)
    link_path = os.path.join(NGINX_SITES_ENABLED, domain)
    if os.path.exists(link_path):
        print(f"Link simbólico já existe para {domain}")
        return True
    if os.path.exists(config_path):
        # ATENÇÃO: PERMISSÕES! Precisa rodar com sudo ou ter permissões adequadas.
        result = run_command(['sudo', 'ln', '-s', config_path, link_path])
        return result is not None and result.returncode == 0
    else:
        flash(f"Arquivo de configuração não encontrado para habilitar: {config_path}", 'error')
        return False

def reload_nginx():
    """Recarrega a configuração do Nginx."""
    # ATENÇÃO: PERMISSÕES!
    result = run_command(['sudo', 'systemctl', 'reload', 'nginx'])
    if result and result.returncode == 0:
         flash("Nginx recarregado com sucesso.", 'success')
         return True
    else:
         flash("Falha ao recarregar Nginx.", 'error')
         return False

def disable_nginx_site(domain):
    """Remove o link simbólico para desabilitar o site no Nginx."""
    link_path = os.path.join(NGINX_SITES_ENABLED, domain)
    if os.path.exists(link_path):
        result = run_command(['sudo', 'rm', link_path])
        return result is not None and result.returncode == 0
    return True # Já não existe, considera sucesso

def remove_nginx_config(domain):
    """Remove o arquivo de configuração do Nginx de sites-available."""
    config_path = os.path.join(NGINX_SITES_AVAILABLE, domain)
    if os.path.exists(config_path):
        result = run_command(['sudo', 'rm', config_path])
        return result is not None and result.returncode == 0
    return True # Não existe, considera sucesso

def stop_disable_remove_systemd(service_name):
    """Para, desabilita e remove um serviço systemd (APENAS LINUX)."""
    if platform.system() == 'Windows':
        flash("Gerenciamento de serviços Systemd não é suportado no Windows.", "warning")
        print(f"Skipping systemd removal for {service_name} on Windows.")
        return True # Retorna True para não impedir a remoção do site no JSON

    # Verifica se o diretório SYSTEMD_SERVICE_DIR existe (indicativo de systemd)
    if not os.path.isdir(SYSTEMD_SERVICE_DIR):
         flash(f"Diretório de serviços systemd ({SYSTEMD_SERVICE_DIR}) não encontrado. Pulando gerenciamento de serviço.", 'warning')
         return True

    service_file_path = os.path.join(SYSTEMD_SERVICE_DIR, service_name)
    if not service_name or not os.path.exists(service_file_path):
        print(f"Serviço systemd '{service_name}' não encontrado ou já removido.")
        return True # Se não existe, considera sucesso na remoção

    print(f"Parando serviço: {service_name}")
    run_command(['sudo', 'systemctl', 'stop', service_name], check=False) # Não falha se já estiver parado
    print(f"Desabilitando serviço: {service_name}")
    run_command(['sudo', 'systemctl', 'disable', service_name], check=False) # Não falha se já estiver desabilitado
    service_path = os.path.join(SYSTEMD_SERVICE_DIR, service_name)
    print(f"Removendo arquivo do serviço: {service_path}")
    result = run_command(['sudo', 'rm', service_path])
    if result and result.returncode == 0:
        print(f"Serviço {service_name} removido com sucesso.")
        run_command(['sudo', 'systemctl', 'daemon-reload']) # Recarrega após remover
        run_command(['sudo', 'systemctl', 'reset-failed']) # Limpa estado de falha se houver
        return True
    else:
        flash(f"Falha ao remover o arquivo do serviço systemd: {service_name}", 'error')
        # Tenta recarregar daemon mesmo assim
        run_command(['sudo', 'systemctl', 'daemon-reload'], check=False)
        run_command(['sudo', 'systemctl', 'reset-failed'], check=False)
        return False

def disable_nginx_site(domain):
    """Remove o link simbólico para desabilitar o site no Nginx."""
    link_path = os.path.join(NGINX_SITES_ENABLED, domain)
    if os.path.exists(link_path):
        result = run_command(['sudo', 'rm', link_path])
        return result is not None and result.returncode == 0
    return True # Já não existe, considera sucesso

def remove_nginx_config(domain):
    """Remove o arquivo de configuração do Nginx de sites-available."""
    config_path = os.path.join(NGINX_SITES_AVAILABLE, domain)
    if os.path.exists(config_path):
        result = run_command(['sudo', 'rm', config_path])
        return result is not None and result.returncode == 0
    return True # Não existe, considera sucesso

def stop_disable_remove_systemd(service_name):
    """Para, desabilita e remove um serviço systemd (APENAS LINUX)."""
    if platform.system() == 'Windows':
        flash("Gerenciamento de serviços Systemd não é suportado no Windows.", "warning")
        print(f"Skipping systemd removal for {service_name} on Windows.")
        return True # Retorna True para não impedir a remoção do site no JSON

    # Verifica se o diretório SYSTEMD_SERVICE_DIR existe (indicativo de systemd)
    if not os.path.isdir(SYSTEMD_SERVICE_DIR):
         flash(f"Diretório de serviços systemd ({SYSTEMD_SERVICE_DIR}) não encontrado. Pulando gerenciamento de serviço.", 'warning')
         return True

    service_file_path = os.path.join(SYSTEMD_SERVICE_DIR, service_name)
    if not service_name or not os.path.exists(service_file_path):
        print(f"Serviço systemd '{service_name}' não encontrado ou já removido.")
        return True # Se não existe, considera sucesso na remoção

    print(f"Parando serviço: {service_name}")
    run_command(['sudo', 'systemctl', 'stop', service_name], check=False) # Não falha se já estiver parado
    print(f"Desabilitando serviço: {service_name}")
    run_command(['sudo', 'systemctl', 'disable', service_name], check=False) # Não falha se já estiver desabilitado
    service_path = os.path.join(SYSTEMD_SERVICE_DIR, service_name)
    print(f"Removendo arquivo do serviço: {service_path}")
    result = run_command(['sudo', 'rm', service_path])
    if result and result.returncode == 0:
        print(f"Serviço {service_name} removido com sucesso.")
        run_command(['sudo', 'systemctl', 'daemon-reload']) # Recarrega após remover
        run_command(['sudo', 'systemctl', 'reset-failed']) # Limpa estado de falha se houver
        return True
    else:
        flash(f"Falha ao remover o arquivo do serviço systemd: {service_name}", 'error')
        # Tenta recarregar daemon mesmo assim
        run_command(['sudo', 'systemctl', 'daemon-reload'], check=False)
        run_command(['sudo', 'systemctl', 'reset-failed'], check=False)
        return False


def create_systemd_service(domain, command, port, workdir=None):
    """Cria e habilita um serviço systemd para a aplicação."""
    service_name = f"site-{domain.replace('.', '-')}.service"
    service_path = os.path.join(SYSTEMD_SERVICE_DIR, service_name)

    # Determina o diretório de trabalho
    if not workdir:
        # Tenta adivinhar pelo comando (se for path absoluto)
        if os.path.isabs(command.split()[0]) and '/' in command.split()[0]:
             workdir = os.path.dirname(command.split()[0])
             # Se for um binário em venv/bin, sobe um nível
             if workdir.endswith('/bin'):
                 workdir = os.path.dirname(workdir)
        else:
             # Se não, usa o home do usuário que roda o Flask (PODE NÃO SER O IDEAL!)
             try:
                 # Tenta obter o usuário que está executando o script
                 # Isso pode falhar dependendo de como o script é executado (ex: sudo direto)
                 user_info = pwd.getpwuid(os.geteuid())
                 workdir = user_info.pw_dir
                 flash(f"Diretório de trabalho não especificado, usando home do usuário atual: {workdir}. Considere especificar.", "warning")
             except KeyError:
                 workdir = "/tmp" # Fallback muito básico
                 flash("Não foi possível determinar o diretório home do usuário. Usando /tmp como WorkDir. Especifique um diretório!", "error")

    # Substitui {{PORTA}} no comando, se existir
    final_command = command.replace('{{PORTA}}', str(port))

    # Usuário para rodar o serviço - Idealmente um usuário não-root dedicado
    # Aqui usamos o usuário que roda o Flask (PODE NÃO SER O IDEAL!)
    run_user = pwd.getpwuid(os.geteuid()).pw_name
    print(f"Serviço systemd rodará como usuário: {run_user}")

    service_content = f"""
[Unit]
Description=Serviço para o site {domain}
After=network.target

[Service]
User={run_user}
WorkingDirectory={workdir}
ExecStart={final_command}
Restart=always
Environment=PORT={port}

[Install]
WantedBy=multi-user.target
"""
    try:
        # ATENÇÃO: PERMISSÕES!
        with open(f'/tmp/{service_name}', 'w') as f: # Escreve primeiro em /tmp
             f.write(service_content)
        run_command(['sudo', 'mv', f'/tmp/{service_name}', service_path])
        run_command(['sudo', 'chmod', '644', service_path]) # Permissões padrão

        # Recarrega o daemon, habilita e inicia o serviço
        run_command(['sudo', 'systemctl', 'daemon-reload'])
        run_command(['sudo', 'systemctl', 'enable', service_name])
        result = run_command(['sudo', 'systemctl', 'start', service_name])

        if result and result.returncode == 0:
            flash(f"Serviço systemd '{service_name}' criado e iniciado.", 'success')
            return service_name
        else:
            flash(f"Falha ao iniciar o serviço systemd '{service_name}'. Verifique os logs com 'journalctl -u {service_name}'", 'error')
            return None

    except Exception as e:
        flash(f"Erro ao criar/gerenciar serviço systemd '{service_name}': {e}", 'error')
        return None

def get_public_ip():
    ip = requests.get('https://api.ipify.org').text
    return ip

def get_ssl_cert(domain, email):
    """Solicita um certificado SSL usando Certbot."""
    if not email:
        flash("Email do administrador é necessário para obter certificado SSL.", "error")
        return False

    # ATENÇÃO: PERMISSÕES! Precisa rodar certbot com privilégios.
    # --nginx: Usa o plugin nginx para configurar automaticamente
    # --non-interactive: Não pede confirmação
    # --agree-tos: Aceita os termos de serviço
    # -m: Email para notificações (expiração, etc.)
    # -d: Domínio(s) para o certificado
    # --redirect: (Opcional) Força HTTPS redirecionando HTTP
    command = [
        'sudo', 'certbot', '--nginx', '--non-interactive', '--agree-tos',
        '-m', email, '-d', domain, '--redirect'
    ]
    result = run_command(command)
    if result and result.returncode == 0:
        flash(f"Certificado SSL obtido e configurado para {domain}.", 'success')
        return True
    else:
        flash(f"Falha ao obter certificado SSL para {domain}. Verifique a saída do Certbot.", 'error')
        # Tenta recarregar o nginx mesmo assim, caso o certbot tenha modificado algo mas falhado
        reload_nginx()
        return False


# --- Rotas Flask ---

# --- Rotas de Autenticação ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Exibe o formulário de login e processa a tentativa de login."""
    if 'username' in session:
        return redirect(url_for('index')) # Redireciona se já estiver logado

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("Usuário e senha são obrigatórios.", 'error')
            return render_template('login.html')

        users = load_users()
        user = next((u for u in users if u['username'] == username), None)

        if user and verify_password(user['password'], password):
            session['username'] = user['username']
            flash(f"Login bem-sucedido! Bem-vindo, {user['username']}.", 'success')
            return redirect(url_for('index'))
        else:
            flash("Usuário ou senha inválidos.", 'error')
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout')
def logout():
    """Faz logout do usuário limpando a sessão."""
    session.pop('username', None)
    flash("Você foi desconectado com sucesso.", 'info')
    return redirect(url_for('login'))


# --- Rotas Protegidas ---

@app.route('/system_stats_history')
@login_required
def system_stats_history():
    """Retorna os logs de estatísticas do sistema em JSON."""
    try:
        logs = load_system_logs()
        # Opcional: Poderíamos filtrar/processar os logs aqui se necessário
        # Por exemplo, garantir que os timestamps são facilmente consumíveis pelo JS
        # Mas o formato ISO 8601 UTC já é bom.
        return jsonify(logs)
    except Exception as e:
        print(f"Erro ao obter histórico de estatísticas: {e}")
        # Retorna um objeto de erro ou vazio em caso de falha
        return jsonify({"error": str(e), 'log_5min': [], 'log_30min': [], 'log_24h': []}), 500


@app.route('/')
@login_required
def index():
    """Exibe a página inicial com a lista de sites, IP público e usuários (se admin)."""
    sites = load_sites()
    public_ip = get_public_ip() # Busca o IP público

    # Carrega usuários se o usuário logado for 'cico' para disponibilizar na aba
    users_list = None
    if session.get('username') == 'cico':
        users_list = load_users()

    # Passa sites, IP e usuários (se aplicável) para o template
    return render_template('index.html', sites=sites, public_ip=public_ip, users=users_list)


# Rota única para estatísticas do sistema
@app.route('/system_stats')
@login_required # Proteger a rota de estatísticas
def system_stats():
    """Retorna as estatísticas atuais do sistema em JSON."""
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/') # Uso do disco raiz '/'
        stats = {
            'cpu_usage': cpu,
            'memory_usage': memory.percent,
            'memory_total': round(memory.total / (1024**3), 2), # GB
            'memory_used': round(memory.used / (1024**3), 2),   # GB
            'disk_usage': disk.percent,
            'disk_total': round(disk.total / (1024**3), 2),     # GB
            'disk_used': round(disk.used / (1024**3), 2)        # GB
        }
        return jsonify(stats)
    except Exception as e:
        print(f"Erro ao obter estatísticas do sistema: {e}")
        # Retorna um objeto de erro ou valores padrão em caso de falha
        return jsonify({"error": str(e), "cpu_usage": 0, "memory_usage": 0, "disk_usage": 0}), 500

@app.route('/add_site', methods=['POST'])
@login_required
def add_site():
    """Processa o formulário para adicionar um novo site."""
    domain = request.form.get('domain', '').strip().lower()
    site_type = request.form.get('site_type')
    get_ssl = request.form.get('get_ssl') == 'true'
    admin_email = request.form.get('admin_email', '').strip()

    # Validação básica
    if not domain:
        flash("O domínio é obrigatório.", 'error')
        return redirect(url_for('index'))

    sites = load_sites()
    if any(site['domain'] == domain for site in sites):
        flash(f"O domínio '{domain}' já existe.", 'error')
        return redirect(url_for('index'))

    if get_ssl and not admin_email:
         flash("É necessário fornecer um email para obter certificado SSL.", 'error')
         return redirect(url_for('index'))


    new_site_data = {
        "domain": domain,
        "type": site_type,
        "ssl_enabled": False # Inicialmente falso
    }
    nginx_config_path = None
    service_name = None

    # --- Lógica para PHP ---
    if site_type == 'php':
        path = request.form.get('path', '').strip()
        if not path:
            flash("O caminho para os arquivos PHP é obrigatório.", 'error')
            return redirect(url_for('index'))
        if '..' in path or not path.startswith('/'): # Medida de segurança básica
             flash("Caminho inválido.", 'error')
             return redirect(url_for('index'))

        new_site_data['path'] = path

        # 1. Criar diretório (se não existir)
        # ATENÇÃO: PERMISSÕES! O usuário que roda o Flask precisa poder escrever no diretório pai (ex: /var/www)
        try:
            # Cria o diretório com permissão para o Nginx (geralmente www-data) ler
            # run_command(['sudo', 'mkdir', '-p', path]) # Cria diretório
            # run_command(['sudo', 'chown', f'www-data:www-data', path]) # Define dono (ajuste www-data se necessário)
            # run_command(['sudo', 'chmod', '755', path]) # Permissões
            # **Abordagem alternativa mais simples (mas menos segura se o Flask roda como root):**
            os.makedirs(path, exist_ok=True) # Cria diretório (se rodar como root, pertence a root)
            # Idealmente, ajustar permissões depois com chown/chmod
            flash(f"Diretório '{path}' criado (ou já existia). Verifique as permissões!", 'info') # Avisa sobre permissões
        except Exception as e:
            flash(f"Erro ao criar diretório '{path}': {e}", 'error')
            return redirect(url_for('index'))

        # 2. Gerar config Nginx
        nginx_config_path = generate_nginx_config('php_site.conf', domain, root_path=path)
        if not nginx_config_path:
             # Erro já foi sinalizado pela função
             return redirect(url_for('index'))

    # --- Lógica para Python/Node.js ---
    elif site_type == 'python_node':
        try:
            port = int(request.form.get('port'))
        except (ValueError, TypeError):
            flash("A porta deve ser um número válido.", 'error')
            return redirect(url_for('index'))

        command = request.form.get('command', '').strip()
        workdir = request.form.get('workdir', '').strip() or None # Pega o workdir ou None

        if not command:
            flash("O comando de inicialização é obrigatório.", 'error')
            return redirect(url_for('index'))
        if workdir and ('..' in workdir or not workdir.startswith('/')):
             flash("Diretório de trabalho inválido.", 'error')
             return redirect(url_for('index'))

        new_site_data['port'] = port
        new_site_data['command'] = command
        new_site_data['workdir'] = workdir


        # 1. Gerar config Nginx (Reverse Proxy)
        nginx_config_path = generate_nginx_config('proxy_site.conf', domain, port=port)
        if not nginx_config_path:
            return redirect(url_for('index'))

        # 2. Criar e iniciar serviço Systemd
        service_name = create_systemd_service(domain, command, port, workdir)
        if not service_name:
            # Tentar limpar a config do Nginx se falhou em criar o serviço? (Opcional)
            # run_command(['sudo', 'rm', nginx_config_path], check=False)
            return redirect(url_for('index'))
        new_site_data['service_name'] = service_name

    else:
        flash("Tipo de site inválido.", 'error')
        return redirect(url_for('index'))

    # --- Passos Comuns (Nginx enable, reload, SSL) ---

    # 3. Habilitar site no Nginx
    if not enable_nginx_site(domain):
        flash(f"Falha ao habilitar o site {domain} no Nginx.", 'error')
        # Limpar? Remover config, parar/desabilitar serviço?
        if service_name: run_command(['sudo', 'systemctl', 'stop', service_name], check=False)
        if service_name: run_command(['sudo', 'systemctl', 'disable', service_name], check=False)
        if nginx_config_path and os.path.exists(nginx_config_path): run_command(['sudo', 'rm', nginx_config_path], check=False)
        return redirect(url_for('index'))

    # 4. Recarregar Nginx (inicialmente para HTTP)
    if not reload_nginx():
        # Se falhar aqui, o link simbólico existe, mas o Nginx não recarregou
        # Tentar desfazer?
        link_path = os.path.join(NGINX_SITES_ENABLED, domain)
        if os.path.exists(link_path): run_command(['sudo', 'rm', link_path], check=False)
        # Parar serviço etc...
        return redirect(url_for('index'))

    # 5. Obter SSL (se solicitado)
    if get_ssl:
        ssl_success = get_ssl_cert(domain, admin_email)
        # O Certbot (com --nginx) deve ter modificado a config e recarregado o Nginx
        new_site_data['ssl_enabled'] = ssl_success
        if not ssl_success:
             flash(f"O site {domain} foi criado, mas houve falha ao obter o certificado SSL. O site pode estar acessível via HTTP.", "warning")
             # O site ainda pode funcionar em HTTP, então não desfazemos tudo necessariamente.
    else:
         flash(f"Site {domain} criado com sucesso (HTTP apenas).", 'success')


    # Adiciona o usuário que criou o site aos dados
    new_site_data['created_by_user'] = session.get('username')

    # 6. Salvar dados do site (ANTES de permissões/link para ter o registro mesmo se falharem)
    sites.append(new_site_data) # REMOVIDA A LINHA DUPLICADA AQUI
    save_sites(sites)

    # --- Passos Adicionais: Permissões e Link Simbólico (APÓS salvar no JSON) ---
    if platform.system() == 'Linux':
        logged_in_user = session.get('username')
        target_directory = None
        if site_type == 'php' and path:
            target_directory = path
        elif site_type == 'python_node' and workdir: # Usa workdir se fornecido
            target_directory = workdir
        elif site_type == 'python_node' and path: # Fallback para path se workdir não foi dado mas path existe (caso de guess)
             target_directory = path

        if logged_in_user and target_directory:
             print(f"Tentando aplicar pós-configuração para usuário '{logged_in_user}' e diretório '{target_directory}'")
             # 7. Definir permissões no diretório para o usuário logado
             set_directory_permissions(target_directory, logged_in_user)

             # 8. Criar link simbólico na home do usuário logado
             create_home_symlink(target_directory, logged_in_user, domain)
        else:
             print("Skipping permission/symlink steps: Linux only, requires logged-in user and target directory.")
             if not logged_in_user: flash("Não foi possível determinar o usuário logado para permissões/link.", "warning")
             if not target_directory: flash("Diretório alvo não determinado para permissões/link.", "warning")

    # 9. Redirecionar para a página inicial
    # Flash messages já foram adicionadas pelas funções auxiliares
    return redirect(url_for('index'))


@app.route('/delete_site/<domain>', methods=['POST'])
@login_required
def delete_site(domain):
    """Remove um site existente."""
    sites = load_sites()
    site_to_delete = None
    for site in sites:
        if site['domain'] == domain:
            site_to_delete = site
            break

    if not site_to_delete:
        flash(f"Site com domínio '{domain}' não encontrado.", 'error')
        return redirect(url_for('index'))

    print(f"Iniciando exclusão do site: {domain}")

    # 1. Parar, desabilitar e remover serviço Systemd (se aplicável)
    systemd_removed = True # Assume sucesso se não for python/node
    if site_to_delete.get('service_name'):
        systemd_removed = stop_disable_remove_systemd(site_to_delete['service_name'])
        if not systemd_removed:
             flash(f"Falha ao remover completamente o serviço systemd para {domain}. Verifique manualmente.", 'warning')
             # Continua mesmo assim? Ou para? Por enquanto, continua.

    # 2. Desabilitar site no Nginx (remover link simbólico)
    nginx_disabled = disable_nginx_site(domain)
    if not nginx_disabled:
        flash(f"Falha ao desabilitar o site {domain} no Nginx (remover link simbólico).", 'error')
        # Poderia parar aqui, mas vamos tentar remover a config mesmo assim

    # 3. Remover configuração do Nginx (arquivo em sites-available)
    nginx_config_removed = remove_nginx_config(domain)
    if not nginx_config_removed:
         flash(f"Falha ao remover o arquivo de configuração {domain} de sites-available.", 'error')

    # 4. Recarregar Nginx (importante após desabilitar/remover)
    nginx_reloaded = reload_nginx()
    if not nginx_reloaded:
        flash("Falha ao recarregar o Nginx após modificações.", 'warning')

    # 5. Remover dados do site do JSON
    sites = [s for s in sites if s['domain'] != domain]
    save_sites(sites)

    # --- Passos Adicionais de Remoção (Pós JSON) ---

    created_by_user = site_to_delete.get('created_by_user')
    directory_to_remove = None
    if site_to_delete.get('type') == 'php':
        directory_to_remove = site_to_delete.get('path')
    elif site_to_delete.get('type') == 'python_node':
        directory_to_remove = site_to_delete.get('workdir') # Prioriza workdir para apps

    # 5. Remover Link Simbólico da Home (Linux apenas)
    if platform.system() == 'Linux' and created_by_user:
        try:
            site_link_name = domain.replace('.', '-')
            user_info = pwd.getpwnam(created_by_user)
            symlink_path = os.path.join(user_info.pw_dir, site_link_name)
            if os.path.islink(symlink_path): # Verifica se é um link antes de tentar remover
                print(f"Tentando remover link simbólico: {symlink_path}")
                result_rm_link = run_command(['sudo', 'rm', symlink_path], check=False)
                if result_rm_link and result_rm_link.returncode == 0:
                    flash(f"Link simbólico '{symlink_path}' removido da home de '{created_by_user}'.", 'info')
                else:
                    flash(f"Falha ao remover link simbólico '{symlink_path}'. Detalhes: {result_rm_link.stderr if result_rm_link else 'N/A'}", 'warning')
            # else: # Opcional: Informar se o link não existia
            #    print(f"Link simbólico '{symlink_path}' não encontrado ou não é um link.")
        except KeyError:
            flash(f"Aviso: Usuário do sistema '{created_by_user}' associado ao site não encontrado. Não foi possível remover o link simbólico da home.", 'warning')
        except Exception as e:
            print(f"Erro ao tentar remover link simbólico para {domain} do usuário {created_by_user}: {e}")
            flash(f"Aviso: Erro inesperado ao tentar remover o link simbólico para {domain}.", 'warning')

    # 6. Remover Diretório do Site (/var/www/... ou workdir) - AÇÃO DESTRUTIVA!
    if directory_to_remove:
        # AVISO IMPORTANTE!
        flash(f"AVISO: Tentando remover o diretório do site '{directory_to_remove}'. Esta ação é PERMANENTE e IRREVERSÍVEL!", "danger")
        print(f"Tentando remover o diretório recursivamente: {directory_to_remove}")
        # Verifica se o diretório existe antes de tentar remover
        if os.path.isdir(directory_to_remove):
            # Usa sudo rm -rf pois pode ter sido criado por root ou outro usuário
            result_rm_dir = run_command(['sudo', 'rm', '-rf', directory_to_remove], check=False)
            if result_rm_dir and result_rm_dir.returncode == 0:
                flash(f"Diretório '{directory_to_remove}' removido com sucesso.", 'success') # Mudei para success para clareza
            else:
                flash(f"ERRO: Falha ao remover o diretório '{directory_to_remove}'. Verifique permissões ou remova manualmente. Detalhes: {result_rm_dir.stderr if result_rm_dir else 'N/A'}", 'error')
        else:
             flash(f"Diretório '{directory_to_remove}' não encontrado ou não é um diretório. Remoção do diretório pulada.", 'info')
    else:
         print(f"Nenhum diretório principal (path/workdir) associado encontrado no JSON para remoção do site {domain}.")


    flash(f"Site '{domain}' removido do painel. Tentativa de remoção de serviço, configurações Nginx, link simbólico e diretório realizada.", 'success') # Mensagem final ajustada

    return redirect(url_for('index'))


# --- Rotas de Gerenciamento de Usuários (Somente Admin) ---

@app.route('/users')
@login_required
@admin_required
def users_management_page(): # Renomeei a função para evitar conflito interno de nome com a variável 'users'
    """Exibe a página de gerenciamento de usuários (apenas para 'cico')."""
    # Esta rota agora renderiza a página principal,
    # mas o template index.html usará os dados passados para popular a aba correta.
    all_users = load_users()
    sites = load_sites() # Carrega sites para passar ao template principal
    public_ip = get_public_ip()
    # Indica qual aba deve estar ativa no template
    active_tab = 'users'
    # Renderiza o template principal, passando os dados necessários e a aba ativa
    return render_template('index.html', sites=sites, public_ip=public_ip, users=all_users, active_tab=active_tab)


@app.route('/add_user', methods=['POST'])
@login_required
@admin_required
def add_user():
    """Adiciona um novo usuário ao painel e ao sistema (Linux)."""
    username = request.form.get('new_username', '').strip()
    password = request.form.get('new_password', '').strip()

    if not username or not password:
        flash("Nome de usuário e senha são obrigatórios.", 'error')
        return redirect(url_for('users_management_page'))

    if username == 'cico': # Impede criação duplicada do admin
         flash("Não é permitido criar outro usuário com o nome 'cico'.", 'error')
         return redirect(url_for('users_management_page'))

    users_list = load_users()
    if any(u['username'] == username for u in users_list):
        flash(f"Erro: O nome de usuário '{username}' já está em uso no painel.", 'error')
        return redirect(url_for('users_management_page'))

    system_user_created = False
    if platform.system() == 'Linux':
        # 1. Tentar criar o usuário no sistema
        #    -m: Cria diretório home
        #    -s /bin/bash: Permite login interativo (SSH). Use /sbin/nologin se o usuário não precisar de acesso SSH.
        #    -m: Cria o diretório home
        print(f"Tentando criar usuário do sistema: {username}")
        cmd_useradd = ['sudo', 'useradd', '-m', '-s', '/bin/bash', username] # Permite login interativo (SSH)
        result_useradd = run_command(cmd_useradd, check=False) # check=False para tratar erro manualmente

        if result_useradd is not None and result_useradd.returncode == 0:
            # 2. Tentar definir a senha do usuário do sistema
            print(f"Usuário {username} criado, definindo senha...")
            # Usa chpasswd para definir a senha de forma não interativa
            # CUIDADO: Isso envolve passar a senha via pipe ou similar.
            cmd_passwd = f"echo '{username}:{password}' | sudo chpasswd"
            # run_command atual não lida bem com pipes no comando diretamente, usamos shell=True com cuidado
            result_passwd = run_command(cmd_passwd, check=False, shell=True)

            if result_passwd is not None and result_passwd.returncode == 0:
                print(f"Senha definida para o usuário do sistema {username}.")
                system_user_created = True
            else:
                # Falha ao definir senha: tenta remover o usuário criado para não deixar órfão
                flash(f"Erro ao definir a senha para o usuário do sistema '{username}'. Removendo usuário criado...", 'error')
                print(f"Erro ao definir senha para {username}. Tentando remover com userdel...")
                run_command(['sudo', 'userdel', '-r', username], check=False) # Tenta remover, ignora falha aqui
                # Não salva no JSON e redireciona com erro
                return redirect(url_for('users_management_page'))
        else:
            # Falha ao criar usuário (pode já existir no sistema, ou outro erro)
            error_msg = f"Erro ao criar o usuário do sistema '{username}'."
            if result_useradd and "já existe" in result_useradd.stderr.lower():
                 error_msg = f"O usuário '{username}' já existe no sistema operacional."
            elif result_useradd:
                 error_msg += f" Detalhes: {result_useradd.stderr}"
            flash(error_msg, 'error')
            # Não salva no JSON e redireciona com erro
            return redirect(url_for('users_management_page'))

    elif platform.system() != 'Linux':
        flash(f"Aviso: Executando em sistema não-Linux ({platform.system()}). Usuário do sistema operacional não será criado.", 'warning')
        # Permite continuar para criar apenas o usuário do painel

    # 3. Se a criação no sistema foi bem-sucedida (ou se não for Linux), adiciona ao JSON
    if system_user_created or platform.system() != 'Linux':
        users_list.append({"username": username, "password": password})
        save_users(users_list)
        if system_user_created:
            flash(f"Usuário '{username}' adicionado com sucesso ao painel e ao sistema (com shell /bin/bash para acesso SSH).", 'success')
        else: # Caso não seja Linux
            flash(f"Usuário '{username}' adicionado com sucesso ao painel (usuário do sistema não criado/verificado).", 'success')
    # Se system_user_created for False e for Linux, o erro já foi tratado e redirecionado acima.

    return redirect(url_for('users_management_page'))


@app.route('/delete_user/<username>', methods=['POST'])
@login_required
@admin_required
def delete_user(username):
    """Remove um usuário do painel e do sistema (Linux)."""
    if username == 'cico':
        flash("Não é possível remover o usuário administrador 'cico'.", 'error')
        return redirect(url_for('users_management_page'))

    users_list = load_users()
    user_to_delete = next((u for u in users_list if u['username'] == username), None)

    if not user_to_delete:
        flash(f"Usuário '{username}' não encontrado no painel.", 'error')
        return redirect(url_for('users_management_page'))

    system_user_deleted = False
    if platform.system() == 'Linux':
        # 1. Tentar remover o usuário do sistema
        #    -r: Remove o diretório home e o spool de email
        print(f"Tentando remover usuário do sistema: {username}")
        cmd_userdel = ['sudo', 'userdel', '-r', username]
        result_userdel = run_command(cmd_userdel, check=False) # check=False para tratar erro manualmente

        if result_userdel is not None and result_userdel.returncode == 0:
            print(f"Usuário do sistema '{username}' removido com sucesso.")
            system_user_deleted = True
        # Trata caso onde o usuário não existe no sistema (ainda considera sucesso para remover do painel)
        elif result_userdel and ("não existe" in result_userdel.stderr.lower() or "does not exist" in result_userdel.stderr.lower()):
             print(f"Usuário do sistema '{username}' não encontrado. Procedendo com remoção do painel.")
             system_user_deleted = True # Considera como 'sucesso' para o fluxo do painel
        else:
            # Falha ao remover usuário do sistema por outra razão
            error_msg = f"Erro ao remover o usuário do sistema '{username}'."
            if result_userdel:
                 error_msg += f" Detalhes: {result_userdel.stderr}"
            flash(error_msg, 'error')
            # Não remove do JSON e redireciona com erro
            return redirect(url_for('users_management_page'))

    elif platform.system() != 'Linux':
        flash(f"Aviso: Executando em sistema não-Linux ({platform.system()}). Usuário do sistema operacional não será removido.", 'warning')
        # Permite continuar para remover apenas o usuário do painel

    # 2. Se a remoção do sistema foi bem-sucedida (ou não aplicável), remove do JSON
    if system_user_deleted or platform.system() != 'Linux':
        users_list = [u for u in users_list if u['username'] != username]
        save_users(users_list)
        if system_user_deleted and platform.system() == 'Linux':
            flash(f"Usuário '{username}' removido com sucesso do painel e do sistema.", 'success')
        else:
             flash(f"Usuário '{username}' removido com sucesso do painel (usuário do sistema não removido/verificado).", 'success')

    # Se system_user_deleted for False e for Linux, o erro já foi tratado e redirecionado acima.

    return redirect(url_for('users_management_page'))


# --- Ponto de Entrada da Aplicação ---

if __name__ == '__main__':
    # --- Inicia a thread de logging em background ---
    # Roda a primeira vez imediatamente para ter dados iniciais
    log_system_stats()
    # Cria e inicia a thread como daemon (encerra junto com o app principal)
    scheduler_thread = threading.Thread(target=run_logging_scheduler, daemon=True)
    scheduler_thread.start()

    # ATENÇÃO: Rodar com 0.0.0.0 expõe na rede. Use 127.0.0.1 para acesso local apenas.
    #          O ideal é usar um servidor WSGI como Gunicorn ou Waitress por trás de um Nginx.
    #          Rodar com debug=True NÃO é seguro em produção.
    #          debug=True faz o Flask reiniciar, o que pode reiniciar a thread de log também.
    #          Para produção, use debug=False e um servidor WSGI.
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False) # use_reloader=False evita que o scheduler reinicie com cada mudança no código durante o dev com debug=True
    # Para produção real:
    # app.run(host='127.0.0.1', port=5000, debug=False) # Ou use Gunicorn/Waitress
