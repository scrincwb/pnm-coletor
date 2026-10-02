#!/usr/bin/env bash
# Conferência de estoque nas páginas das lojas, feita PELO GITHUB (scripts/estoque_runner.py):
# as lojas bloqueiam o IP do servidor (Roma, Mega, Madrid Center, Cellshop…) e o servidor
# corta pedido em 120 s. O servidor só diz o que conferir e grava o resultado.
# Usado pelo job "feeds" e pelo job "estoque" (a cada 6 h e manual).
set -u
python3 "$(dirname "$0")/estoque_runner.py"
