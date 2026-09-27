# pnm-coletor

Agendador público da coleta de preços do **Paraguai na Mão**. Aqui fica **só** o
workflow (`.github/workflows/coletor.yml`); o código do robô continua no repositório
privado `scrincwb/paraguainamao-site` (pasta `coletor/`) e é baixado na hora com
uma chave somente-leitura. Repositório público = minutos do GitHub Actions grátis.

Secrets: `SITE_DEPLOY_KEY` (chave SSH de leitura do repo do site) e `COLETOR_TOKEN`
(Admin › Lojas › token de escopo coletor).
