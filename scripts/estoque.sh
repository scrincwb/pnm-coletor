#!/usr/bin/env bash
# Conferência de estoque nas páginas das lojas (feita pelo servidor, em paralelo,
# cada chamada para sozinha em ~80 s porque o servidor corta em 120 s).
# Usado pelo job "feeds" e pelo modo manual "estoque".
set -u
chamar() { curl -sS --max-time 150 -A "$UA_NAV" -H "Authorization: Bearer $COLETOR_TOKEN" "$COLETOR_API_URL?$1" || true; echo; }
# Lojas cuja lista/feed não diz a verdade sobre o estoque: a página decide.
#   Roma: lista sem estoque · Shopping China: feed diz "Em estoque" para tudo
#   Mega: JSON-LD diz InStock (preço US$ 1) em produto esgotado; vale o selo da página
# Sax fora (out/2026): site em "Catálogo en actualización", sem estoque na página e 403 para o servidor.
for i in 1 2 3 4 5 6 7 8; do chamar "acao=verificar_estoque&loja=roma-shopping&qtd=400"; done
for i in 1 2 3 4 5 6;     do chamar "acao=verificar_estoque&loja=shopping-china&qtd=500"; done
for i in 1 2 3 4;         do chamar "acao=verificar_estoque&loja=mega-eletronicos&qtd=500"; done
# Todas as outras lojas: a oferta mais barata dos produtos mais vistos (relatório por loja).
for i in 1 2 3 4;         do chamar "acao=verificar_estoque_geral&qtd=400"; done
