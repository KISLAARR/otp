# OTP Service

Отдельный микросервис на FastAPI для отправки и проверки одноразовых кодов
подтверждения (SMS / flash-call через SMSC.ru, резерв — SMS.ru). Вызывается
только сервером beauty_platform по HTTP — наружу (в интернет) не публикуется,
живёт в той же docker-сети на одном VPS с beauty_platform (см. деплой ниже).

## API

Все эндпоинты (кроме `/health` и `GET /api/v1/admin/status`) требуют заголовок
`Authorization: Bearer <API_KEY>`.

### POST /api/v1/otp/send

```json
{ "phone": "+79161234567", "method": "sms" }
```

`method`: `sms` или `flash_call`. Ответ:

```json
{
  "request_id": "…",
  "status": "sent",
  "masked_phone": "+7 (916) 123-**-**",
  "expires_in_seconds": 300
}
```

### POST /api/v1/otp/verify

```json
{ "request_id": "…", "code": "1234", "phone": "+79161234567" }
```

Ответ: `{ "valid": true, "message": "Code verified successfully" }`

### GET /api/v1/admin/status — здоровье сервиса (без авторизации)
### GET /api/v1/admin/stats — счётчики (требует авторизацию)

## Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

По умолчанию `SMS_MODE=mock` — код никуда не отправляется, а печатается в
консоль. Это позволяет тестировать `/send` и `/verify` без реального
провайдера и без базы Postgres (используется локальный sqlite-файл).

## Деплой на Timeweb (вместе с beauty_platform, один VPS)

Разворачивается **не самостоятельно** — как ещё один сервис в
`docker-compose.prod.yml` репозитория beauty_platform. Оба репозитория
должны лежать рядом на сервере:

```
/opt/beauty_platform/   ← git clone beauty_platform, отсюда запускается docker compose
/opt/otp-service/       ← git clone этого репозитория (сосед, тот же уровень)
```

### 1. Управляемая PostgreSQL (Timeweb)

Один кластер на оба приложения — с двумя базами внутри:

1. Панель Timeweb → **Базы данных** → **Создать** → PostgreSQL 15.
2. Заведи администратора кластера (логин/пароль) — этими же кредами будут
   пользоваться обе базы.
3. Создай в кластере две базы: `beauty_platform` и `otp_service`.
4. Скопируй внутренний хост кластера — он пойдёт в `POSTGRES_HOST` в `.env`
   обоих проектов (у otp-service — `DATABASE_URL`, у beauty_platform —
   `POSTGRES_HOST`/`POSTGRES_PORT`).
5. Автоматические ежедневные бэкапы уже включены на стороне Timeweb — это
   основная защита; `backup_to_s3.sh` в beauty_platform (см. его README)
   дублирует дампы в S3 для дополнительной подстраховки.

### 2. Клонирование и .env

```bash
cd /opt
git clone <ссылка на otp-service> otp-service
cd otp-service
cp .env.example .env
# API_KEY — та же случайная строка, что укажешь как OTP_SERVICE_API_KEY
# в beauty_platform/.env
# DATABASE_URL — postgresql+psycopg2://<user>:<password>@<host из панели>:5432/otp_service
# SMS_MODE=mock, пока нет доступов от SMSC.ru — как появятся, меняешь на live
```

### 3. Запуск

Отдельно контейнер не поднимается — он собирается и стартует как сервис
`otp` из `docker-compose.prod.yml` **beauty_platform** (build-контекст —
`../otp-service`, порт наружу не публикуется):

```bash
cd /opt/beauty_platform
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f otp
```

Проверка изнутри сети (со стороны app-контейнера otp недоступен снаружи —
это осознанно, наружу торчит только Caddy/beauty_platform):

```bash
docker compose -f docker-compose.prod.yml exec app python -c \
  "import urllib.request; print(urllib.request.urlopen('http://otp:8000/health').read())"
```

## Безопасность

- Коды не хранятся в открытом виде — только `SHA-256(код + номер)`.
- TTL кода и ограничение попыток проверки (`MAX_VERIFY_ATTEMPTS`).
- Rate limit на отправку по номеру (`RATE_LIMIT_PER_MINUTE`) — сейчас
  in-memory, для нескольких инстансов/реплик нужно будет вынести в Redis.
- `API_KEY` закрывает доступ к `/send`, `/verify`, `/stats`; сервис вообще
  не публикуется в интернет — достучаться до него можно только изнутри
  docker-сети VPS.