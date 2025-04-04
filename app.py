import os
import requests
import subprocess
import json
import platform # Para verificar o sistema operacional
import getpass # Alternativa para obter o usuário atual
# import pwd # Removido - Não funciona no Windows
import psutil # Para obter estatísticas do sistema
import threading
import time
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


    # 6. Salvar dados do site
    sites.append(new_site_data)
    save_sites(sites)

    # 7. Redirecionar para a página inicial
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

    # TODO: Opcional - Remover diretório root (para PHP) ou diretório de trabalho?
    # Isso pode ser perigoso, então deixamos comentado por padrão.
    # if site_to_delete.get('path'):
    #     run_command(['sudo', 'rm', '-rf', site_to_delete['path']], check=False) # MUITO CUIDADO!

    flash(f"Site '{domain}' removido com sucesso (ou tentativa de remoção iniciada).", 'success')
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
    """Adiciona um novo usuário (apenas para 'cico')."""
    username = request.form.get('new_username', '').strip()
    password = request.form.get('new_password', '').strip()

    if not username or not password:
        flash("Nome de usuário e senha são obrigatórios.", 'error')
        # Redireciona de volta para a página de gerenciamento, que mostrará a aba usuários ativa
        return redirect(url_for('users_management_page'))

    users_list = load_users() # Renomeei para evitar conflito
    if any(u['username'] == username for u in users_list):
        flash(f"Erro: O nome de usuário '{username}' já está em uso.", 'error')
        # Redireciona de volta para a página de gerenciamento, que mostrará a aba usuários ativa
        # A rota 'users_management_page' garante que active_tab='users' seja passado ao template.
        return redirect(url_for('users_management_page'))

    # IMPORTANTE: Sem hashing de senha conforme solicitado
    users_list.append({"username": username, "password": password})
    save_users(users_list)
    flash(f"Usuário '{username}' adicionado com sucesso.", 'success')
    # Redireciona de volta para a página de gerenciamento (aba usuários ativa)
    return redirect(url_for('users_management_page'))


@app.route('/delete_user/<username>', methods=['POST'])
@login_required
@admin_required
def delete_user(username):
    """Remove um usuário (apenas para 'cico', não pode remover 'cico')."""
    if username == 'cico':
        flash("Não é possível remover o usuário administrador 'cico'.", 'error')
        # Redireciona de volta para a página de gerenciamento (aba usuários ativa)
        return redirect(url_for('users_management_page'))

    users_list = load_users() # Renomeei para evitar conflito
    user_exists = any(u['username'] == username for u in users_list)

    if not user_exists:
         flash(f"Usuário '{username}' não encontrado.", 'error')
         # Redireciona de volta para a página de gerenciamento (aba usuários ativa)
         return redirect(url_for('users_management_page'))

    users_list = [u for u in users_list if u['username'] != username]
    save_users(users_list)
    flash(f"Usuário '{username}' removido com sucesso.", 'success')
    # Redireciona de volta para a página de gerenciamento (aba usuários ativa)
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
