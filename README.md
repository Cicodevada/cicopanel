# CicoPanel v1

**🇧🇷 PT-BR** | [EN-US](#cicopanel-v1-en-us)

---

## ⚠️ Projeto Descontinuado ⚠️

**Atenção:** O CicoPanel v1 é um projeto que, embora funcional, **não está mais em desenvolvimento ativo e não receberá novas funcionalidades ou atualizações de segurança**.

Eu migrei o desenvolvimento para o **CicoPanel v2**, uma plataforma completamente reescrita que se tornará um produto comercial em breve.

Você é livre para usar, estudar e modificar o CicoPanel v1 por sua conta e risco, mas saiba que ele é considerado um projeto legado.

---

### O que é o CicoPanel?

O CicoPanel é um painel de controle de hospedagem web leve e de código aberto, escrito em Python com o microframework Flask. Ele foi projetado para simplificar o gerenciamento de sites e aplicações em servidores Linux (Debian/Ubuntu), automatizando tarefas comuns através de uma interface web amigável.

### Funcionalidades

*   **Dashboard de Sistema:** Monitore em tempo real e com gráficos históricos o uso de CPU, Memória e Disco.
*   **Gerenciamento de Sites:**
    *   Crie sites PHP com configuração automática de *document root*.
    *   Crie aplicações (Python, Node.js, etc.) com proxy reverso Nginx.
*   **Automação:**
    *   Geração automática de configurações Nginx.
    *   Criação e gerenciamento de serviços `systemd` para suas aplicações.
    *   Integração com Certbot para emissão e renovação de certificados SSL (HTTPS).
*   **Gerenciamento de Usuários:** O administrador (`cico`) pode criar e remover usuários do painel.
*   **Terminal Web Isolado:** Cada usuário recebe uma instância de terminal isolada baseada em Alpine Linux (via PRoot), permitindo acesso seguro ao shell sem expor o sistema hospedeiro.
*   **Gerenciador de Arquivos:** Um gerenciador de arquivos completo via web para cada site, com upload, criação de pastas, renomeação, exclusão, cópia, movimentação e extração de arquivos (`.zip`, `.tar.gz`, etc.).

### Instalação

**Requisitos:**
*   Um servidor com Debian 11/12 ou Ubuntu 20.04/22.04.
*   Acesso root ou um usuário com permissões `sudo`.

**1. Clone o repositório:**
```bash
git clone https://github.com/cicodevada/CicoPanel.git
cd CicoPanel
```

**2. Instale as dependências do sistema:**
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx
```

**3. Crie um ambiente virtual e instale as dependências Python:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**4. Configure o Sudo (Recomendado):**
O painel precisa executar alguns comandos com `sudo`. Para evitar prompts de senha, adicione o usuário que rodará o `app.py` ao arquivo `sudoers`. **Cuidado, isso concede privilégios elevados.**

Execute `sudo visudo` e adicione a seguinte linha, substituindo `seu_usuario` pelo nome do seu usuário:
```
seu_usuario ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/chown, /bin/ln, /bin/rm, /usr/bin/certbot
```

**5. Inicie o painel:**
```bash
python3 app.py
```

### Uso

1.  Acesse o painel no seu navegador: `http://SEU_IP_DO_SERVIDOR:5000`
2.  Use as credenciais padrão para o primeiro login:
    *   **Usuário:** `cico`
    *   **Senha:** `admin`

### Apoie o Projeto
Gostou do CicoPanel v1? Considere me pagar um café!

<a href="https://buymeacoffee.com/cicodevada" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

---
<a name="cicopanel-v1-en-us"></a>

# CicoPanel v1 (EN-US)

[PT-BR](#-projeto-descontinuado-) | **🇺🇸 EN-US**

---

## ⚠️ Deprecated Project ⚠️

**Attention:** CicoPanel v1 is a project that, while functional, **is no longer under active development and will not receive new features or security updates**.

I have shifted development efforts to **CicoPanel v2**, a completely rewritten platform that will soon become a commercial product.

You are free to use, study, and modify CicoPanel v1 at your own risk, but please be aware that it is considered a legacy project.

---

### What is CicoPanel?

CicoPanel is a lightweight, open-source web hosting control panel written in Python using the Flask microframework. It was designed to simplify the management of websites and applications on Linux servers (Debian/Ubuntu) by automating common tasks through a user-friendly web interface.

### Features

*   **System Dashboard:** Monitor CPU, Memory, and Disk usage in real-time with historical graphs.
*   **Site Management:**
    *   Create PHP sites with automatic *document root* configuration.
    *   Create applications (Python, Node.js, etc.) with an Nginx reverse proxy.
*   **Automation:**
    *   Automatic generation of Nginx configurations.
    *   Creation and management of `systemd` services for your applications.
    *   Integration with Certbot for issuing and renewing SSL certificates (HTTPS).
*   **User Management:** The administrator (`cico`) can create and remove panel users.
*   **Isolated Web Terminal:** Each user gets an isolated terminal instance based on Alpine Linux (via PRoot), allowing secure shell access without exposing the host system.
*   **File Manager:** A complete web-based file manager for each site, featuring upload, folder creation, renaming, deletion, copy, move, and archive extraction (`.zip`, `.tar.gz`, etc.).

### Installation

**Requirements:**
*   A server running Debian 11/12 or Ubuntu 20.04/22.04.
*   Root access or a user with `sudo` privileges.

**1. Clone the repository:**
```bash
git clone https://github.com/cicodevada/CicoPanel.git
cd CicoPanel
```

**2. Install system dependencies:**
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx
```

**3. Create a virtual environment and install Python dependencies:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**4. Configure Sudo (Recommended):**
The panel needs to run certain commands with `sudo`. To avoid password prompts, add the user that will run `app.py` to the `sudoers` file. **Be careful, as this grants elevated privileges.**

Run `sudo visudo` and add the following line, replacing `your_user` with your username:
```
your_user ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/chown, /bin/ln, /bin/rm, /usr/bin/certbot
```

**5. Start the panel:**
```bash
python3 app.py
```

### Usage

1.  Access the panel in your browser: `http://YOUR_SERVER_IP:5000`
2.  Use the default credentials for the first login:
    *   **Username:** `cico`
    *   **Password:** `admin`

### Support the Project
Did you like CicoPanel v1? Consider buying me a coffee!

<a href="https://buymeacoffee.com/cicodevada" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
