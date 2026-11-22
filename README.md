# Playlist Generator

Aplicativo desktop (Python + PySide6/Qt) para Windows e Linux. Você escolhe uma pasta
de músicas, gera uma playlist automática com um clique, edita na própria janela e salva
em formatos que o Navidrome entende.

## Instalação

```bash
python -m venv .venv
# Linux:   source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
python -m playlist_generator
```

1. **Pasta de músicas**: seleciona a pasta (busca recursiva). Formatos lidos: flac, mp3,
   wav, ogg, opus, m4a, aac, wma, ape, wv, aiff, mpc e outros.
2. **Playlist**: define o número de faixas (0 = todas) e clica em *Gerar playlist*.
   A ordem é aleatória, sem repetir o mesmo artista em sequência (e, sempre que
   possível, nem o mesmo álbum). Depois você pode adicionar, remover, subir/descer,
   arrastar e soltar, ou limpar.
3. **Salvar**: escolha nome, formato e destino (mesma pasta das músicas ou uma pasta
   dedicada).

## Formatos e Navidrome

| Formato | Observação |
|---------|-----------|
| `.m3u8` / `.m3u` | UTF-8, com `#EXTM3U`, `#PLAYLIST` e `#EXTINF`. Importados pelo Navidrome. |
| `.nsp` | Smart playlist (JSON) com uma regra `filepath` por faixa. Não garante a ordem e o Navidrome lê no máximo 100 KB. |
| `.pls` / `.xspf` | Gerados para uso em outros players. **Não confirmei** que o Navidrome os importe; a documentação consultada cita M3U e NSP. |

Caminhos:
- **Relativo** (padrão): relativo à pasta onde a playlist é salva. O Navidrome resolve
  caminhos relativos a partir da pasta do arquivo, então funciona tanto na pasta das
  músicas quanto em uma pasta dedicada dentro da biblioteca.
- **Absoluto**: use o *prefixo no servidor* se o caminho da música no servidor for
  diferente do deste computador (ex.: `/music`).

O Navidrome só importa playlists que estejam dentro da pasta da biblioteca ou na
pasta definida em `PlaylistsPath`. Uma playlist M3U importada fica somente leitura no
Navidrome enquanto o *Auto-import* estiver ligado.

## Testes

```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest tests
```
