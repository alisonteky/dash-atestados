# Implantação Sem Custo

## Recomendação principal

Para uma produção sem mensalidade, a alternativa mais coerente para este projeto é uma VM Always Free na Oracle Cloud rodando:

- aplicação web Python;
- PostgreSQL local no servidor;
- armazenamento privado em disco para os arquivos Excel;
- proxy HTTPS com Caddy ou Nginx;
- backup criptografado agendado.

Vantagens:

- mantém backend, banco e arquivos no mesmo ambiente;
- não publica dados reais em GitHub Pages;
- permite PostgreSQL real;
- permite logs locais e retenção controlada.

Limites importantes:

- recurso gratuito pode ter restrição de capacidade por região;
- nao substitui plano pago com SLA;
- precisa rotina de backup externo;
- precisa hardening do servidor.

## Alternativa com Supabase Free

Supabase Free pode ser usado para homologação com PostgreSQL e Storage, mas os limites atuais tornam a opção mais adequada para MVP controlado do que para produção sensível:

- 500 MB de banco;
- 1 GB de storage;
- pausa por inatividade;
- sem backups automáticos no plano Free.

Use apenas se os arquivos forem pequenos, o acesso for restrito e houver cópia de segurança fora da plataforma.

## Requisitos mínimos de produção

1. Variáveis de ambiente com senha administrativa forte.
2. HTTPS obrigatório.
3. Cookie seguro (`DASH_COOKIE_SECURE=1`).
4. Firewall liberando somente HTTP/HTTPS e SSH restrito.
5. PostgreSQL sem acesso público direto.
6. Diretório `storage/imports/` fora da pasta pública.
7. Backup diário criptografado.
8. Teste de restore mensal.
9. Logs de auditoria preservados.
10. Política de retenção para arquivos importados.

## LGPD

Os arquivos e registros incluem dados pessoais sensíveis de saúde. Antes de uso real:

- definir controlador, operador e encarregado;
- registrar a finalidade do tratamento;
- aplicar menor privilégio nos acessos;
- manter trilha de auditoria;
- restringir exportações;
- documentar retenção e descarte;
- formalizar base legal e política interna.

## Estado técnico atual

O backend já cria as tabelas profissionais e executa upload, pré-validação, confirmação e rollback. Em produção, defina `DATABASE_URL` para ativar PostgreSQL real; sem essa variável, o servidor usa SQLite apenas como fallback local.
