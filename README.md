# Navidrome Playlist Generator

Aplicativo desktop para **Windows** e **Linux** que gera playlists automáticas e inteligentes a partir da sua biblioteca local ou diretamente da sua rede (NAS, Orange Pi, Raspberry Pi, servidores SMB/SFTP) em formatos compatíveis com o **Navidrome**.

---

## 📥 Download e Instalação (Recomendado)

Não é necessário instalar Python nem usar o terminal. Baixe a versão pronta para o seu sistema operacional na página de **[Releases](https://github.com)**:

### 🪟 Windows
1. Baixe o arquivo **`NavidromePlaylistGenerator-Windows.exe`**.
2. Dê dois cliques para executar. *(Caso o Windows SmartScreen exiba um aviso por ser um aplicativo independente, clique em **Mais informações** > **Executar assim mesmo**)*.

### 🐧 Linux (Ubuntu, Linux Mint, Debian e derivados)
1. Baixe o arquivo **`NavidromePlaylistGenerator-Linux.tar.gz`**.
2. Extraia o arquivo (clique com o botão direito > *Extrair aqui*) e dê dois cliques no executável **`NavidromePlaylistGenerator`**.
3. **Dependência necessária (caso a janela não abra):** Em distribuições baseadas no Ubuntu/Debian, certifique-se de ter a biblioteca gráfica instalada:
   ```bash
   sudo apt update && sudo apt install -y libxcb-cursor0
   ```
   *(Para conectar em servidores remotos pelo Linux, também são necessários os pacotes padrão `gvfs`, `gvfs-backends` e `gvfs-fuse`).*

---

## 🚀 Como Usar

1. **Pasta de músicas:** Clique para escolher uma pasta local (busca recursiva). Formatos suportados: `flac`, `mp3`, `wav`, `ogg`, `opus`, `m4a`, `aac`, `wma`, `ape`, `wv`, `aiff`, `mpc`, entre outros.
   * **Conexão com Servidor Remoto:** Se suas músicas ficam em outro computador ou servidor na rede, clique em **Servidor remoto...** e informe o endereço (ex.: `smb://servidor/Musicas` ou `sftp://usuario@host/home/musicas`). Não é preciso montar a unidade antes: o aplicativo conecta, solicita usuário/senha (sem salvar sua senha) e permite navegar pelas subpastas.
     * *No Linux:* Suporta `smb`, `sftp/ssh`, `ftp/ftps`, `dav/davs`, `nfs` e `afp` via GVFS. *(Nota: a leitura de tags pela rede é naturalmente mais lenta que em disco local).*
     * *No Windows:* Suporta compartilhamentos SMB (`\\servidor\pasta`) usando as credenciais do sistema.
2. **Gerar e Editar Playlist:** Defina a quantidade de faixas (`0` = todas) e clique em **Gerar playlist**. O algoritmo embaralha as músicas evitando repetir o mesmo artista em sequência (e, sempre que possível, o mesmo álbum). Depois, você pode adicionar, remover, reordenar arrastando e soltando ou limpar a lista.
3. **Salvar:** Escolha o nome, o formato e a pasta de destino (local ou remota).

---

## 🎵 Formatos Suportados e Dicas para o Navidrome

| Formato | Compatibilidade e Observações |
| :--- | :--- |
| **`.m3u8` / `.m3u`** | **Recomendado.** Codificação UTF-8 com `#EXTM3U`, `#PLAYLIST` e `#EXTINF`. Totalmente suportado pelo Navidrome. |
| **`.nsp`** | Smart Playlist (JSON) com uma regra `filepath` por faixa. Não garante a ordem exata e possui limite de leitura de 100 KB no Navidrome. |
| **`.pls` / `.xspf`** | Gerados para compatibilidade com outros players de desktop. |

### Dicas importantes sobre caminhos no Navidrome:
* **Caminho Relativo (Padrão):** Salva os caminhos das músicas relativos à pasta onde o arquivo da playlist foi gravado. Como o Navidrome resolve caminhos relativos a partir da localização da playlist, funciona perfeitamente tanto na raiz das músicas quanto em subpastas dentro da biblioteca.
* **Caminho Absoluto:** Use a opção *Prefixo no servidor* caso o caminho das músicas dentro do seu servidor (ex.: `/music`) seja diferente do caminho montado no seu computador.
* **Importação:** O Navidrome só importa playlists salvas dentro da pasta da biblioteca ou no diretório configurado em `PlaylistsPath`. Playlists `.m3u`/`.m3u8` importadas ficam como *somente leitura* na interface web enquanto o *Auto-import* estiver ativo.

---

## 🛠️ Executar via Código-Fonte (Desenvolvimento)

Caso queira rodar diretamente pelo Python ou contribuir com o código:

```bash
# 1. Clone o repositório e acesse a pasta
git clone https://github.com
cd Playlist_generator

# 2. Crie e ative o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate      # Linux / macOS
# .venv\Scripts\activate       # Windows

# 3. Instale as dependências e execute
pip install -r requirements.txt
python3 -m playlist_generator
```

### Rodar Testes Automatizados
```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest tests
```
