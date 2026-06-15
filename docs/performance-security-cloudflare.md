# Performance, seguranca e Cloudflare

## O que ja fica ativo no app

- `X-Response-Time-Ms` em toda resposta do backend.
- Log de endpoint lento quando passar de `PERFORMANCE_LOG_SLOW_MS`.
- Headers basicos de seguranca: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` e `Permissions-Policy`.
- `Cache-Control` privado e curto para GETs autenticados.
- Rate limit em login e chamadas de escrita (`POST`, `PUT`, `PATCH`, `DELETE`).
- Segredo opcional para webhooks via `WEBHOOK_SHARED_SECRET`.
- Storage local por padrao, com suporte opcional a Cloudflare R2.

## Cloudflare Free recomendado

1. Adicionar o dominio no Cloudflare.
2. Apontar o DNS para o frontend e backend atuais.
3. Ativar SSL/TLS em modo `Full` ou `Full (strict)` quando o host tiver certificado valido.
4. Ativar protecao DDoS padrao do plano Free.
5. Criar regras de WAF/Firewall:
   - bloquear paises que voce nao atende, se fizer sentido;
   - rate limit ou challenge para `/api/auth/login`;
   - bloquear metodos incomuns fora de `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`;
   - nunca aplicar cache publico em `/api/*` autenticado.
6. Ativar Turnstile no login se houver tentativa de bot ou senha por forca bruta.

## Cloudflare R2 opcional

Use R2 para fotos, anexos e PDFs. Isso tira peso do backend e evita depender do disco local do deploy.

Variaveis necessarias:

```env
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_PUBLIC_BASE_URL=
R2_PRESIGNED_URL_EXPIRE_SECONDS=900
```

Se `R2_PUBLIC_BASE_URL` ficar vazio, o backend gera URL assinada temporaria. Para arquivos sensiveis, prefira URL assinada.

## O que ainda precisa de dado externo

- Dominio real que sera protegido pelo Cloudflare.
- Conta Cloudflare.
- Bucket R2.
- Access Key ID e Secret Access Key do R2.
- Decisao se arquivos serao privados por URL assinada ou publicos via dominio proprio.
- Valor de `WEBHOOK_SHARED_SECRET` e ajuste dos webhooks externos para enviarem o header `x-aquamoab-webhook-secret` ou query `?secret=...`.
