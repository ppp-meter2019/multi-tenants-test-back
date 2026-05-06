# Деплой `tenants_back` за nginx + gunicorn

Покрокова інструкція для прод-розгортання. Замініть `example.com` на ваш
реальний домен і `webmaster` — на потрібного користувача.

Артефакти, що поряд:

| Файл                  | Призначення                                                            |
|-----------------------|------------------------------------------------------------------------|
| `nginx.example.conf`  | віртуальний хост (apex + wildcard сабдомени)                           |
| **`../bin/gunicorn_start.sh`** | bash-launcher для supervisor — основний шлях, inline `export` |
| `gunicorn.conf.py`    | конфіг gunicorn у Python-формі — для systemd-варіанту                  |
| `gunicorn.service`    | альтернатива через systemd                                             |
| `tenants_back.env`    | шаблон env-файлу — використовується **лише** з systemd                 |

---

## 1. Встановити gunicorn

```bash
cd /home/webmaster/tenants_back
source .env/bin/activate
pip install gunicorn   # або додати у requirements.txt
```

---

## 2. Структура каталогів

```
/home/webmaster/tenants_back/                  # код (git checkout цієї теки)
/home/webmaster/tenants_back/.env/             # virtualenv
/home/webmaster/tenants_back/staticfiles/      # collectstatic → сюди
/home/webmaster/tenants_back/run/gunicorn.sock # UNIX-сокет (створюється скриптом)
/home/webmaster/tenants_back/bin/gunicorn_start.sh
/home/webmaster/tenants_front/                 # фронт (vanilla JS)
```

Користувачі/групи:

```bash
sudo useradd -m -s /bin/bash webmaster                      # якщо ще немає
sudo usermod -aG www-data webmaster                          # щоб nginx бачив сокет
sudo install -d -o webmaster -g www-data -m 750 /home/webmaster/tenants_back/run
```

`bin/gunicorn_start.sh` запускається від `webmaster`, але передає
`--user=webmaster --group=www-data --umask=007`. Сокет вийде з правами
`srw-rw----` (читання/запис для `webmaster` і `www-data`).

---

## 3. Основний шлях — supervisor + `bin/gunicorn_start.sh`

### 3.1 Заповнити прод-значення у скрипті

`bin/gunicorn_start.sh` тримає `export DJANGO_*` / `DB_*` **прямо в
тілі скрипта** — без зовнішніх env-файлів. Перед деплоєм відредагуй
блок `--- Production env vars ---`:

```bash
export DJANGO_SECRET_KEY="..."          # openssl rand -hex 50
export DJANGO_DEBUG=0
export DJANGO_ALLOWED_HOSTS=".example.com,example.com"
export DJANGO_CSRF_TRUSTED_ORIGINS="https://example.com,https://*.example.com"
export DJANGO_BEHIND_TLS_PROXY=1
export DJANGO_CORS_ALLOW_ALL=0          # за nginx CORS не потрібен
export DB_PASSWORD="..."                # реальний пароль
```

Решта прапорів gunicorn у самому `exec`:

| Прапор                  | Що робить                                                |
|-------------------------|----------------------------------------------------------|
| `--bind=unix:$SOCKFILE` | UNIX-сокет, що матчиться з nginx `upstream`              |
| `--user=$USER`          | drop privileges → `webmaster`                            |
| `--group=$GROUP`        | runtime group → `www-data` (доступ для nginx)            |
| `--umask=007`           | права на сокет `770` — без world                          |
| `--workers=$NUM_WORKERS`| зазвичай `2*CPU + 1`                                     |
| `--log-file=-`          | пишемо в stdout → supervisor сам ротейтить               |

### 3.2 Sanity-check «руками»

```bash
sudo -u webmaster /home/webmaster/tenants_back/bin/gunicorn_start.sh
# В іншій консолі:
curl --unix-socket /home/webmaster/tenants_back/run/gunicorn.sock \
     http://example.com/api/ -i
```

Якщо відповідає DRF (нехай навіть 401 Unauthorized) — підключаємо
supervisor.

### 3.3 Конфіг supervisor

```ini
; /etc/supervisor/conf.d/tenants_back.conf
[program:tenants_back]
command=/home/webmaster/tenants_back/bin/gunicorn_start.sh
user=webmaster
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/supervisor/tenants_back.log
stdout_logfile_maxbytes=20MB
stdout_logfile_backups=5
stopsignal=TERM
stopasgroup=true
killasgroup=true
```

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status tenants_back
sudo tail -f /var/log/supervisor/tenants_back.log
```

### 3.4 Робочий flow апдейтів

```bash
cd /home/webmaster/tenants_back
sudo -u webmaster git pull
sudo -u webmaster .env/bin/pip install -r requirements.txt
sudo -u webmaster .env/bin/python manage.py migrate_schemas
sudo -u webmaster .env/bin/python manage.py collectstatic --noinput
sudo supervisorctl restart tenants_back
```

---

## 4. nginx

Шаблон — `nginx.example.conf`. Підставити свій домен і шляхи до сертифікатів,
скопіювати в `/etc/nginx/sites-available/tenants.conf`, увімкнути:

```bash
sudo ln -s /etc/nginx/sites-available/tenants.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Ключове в шаблоні:

- `server_name example.com *.example.com;` — один `server { ... }` ловить
  apex і всі сабдомени.
- `upstream tenants_back { server unix:/home/webmaster/tenants_back/run/gunicorn.sock; }`
  — той самий шлях, що в bin-скрипті.
- `location ~ ^/(api|admin)/` → проксі на gunicorn із збереженим `Host`.
  django-tenants дивиться саме на `Host`, щоб обрати схему.
- `location /static/` → `alias /home/webmaster/tenants_back/staticfiles/`.
- `location /` → `root /home/webmaster/tenants_front; try_files $uri $uri/ /index.html;`
  (SPA-фолбек).

---

## 5. TLS

Wildcard-сертифікат від Let's Encrypt через DNS-01:

```bash
sudo certbot certonly --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  -d example.com -d '*.example.com'
```

(Замінити `--dns-cloudflare` на ваш DNS-провайдер; HTTP-01 для wildcard
не підходить.)

---

## 6. Альтернатива — systemd замість supervisor

Якщо supervisor не використовуєте, є готовий юніт `gunicorn.service` +
`gunicorn.conf.py`. У цьому варіанті env-змінні читаються з
`tenants_back.env` (окремий файл, бо саме так systemd інтегрує env
найчистіше — `EnvironmentFile=...`).

```bash
sudo cp /home/webmaster/tenants_back/deploy/gunicorn.service /etc/systemd/system/tenants_back.service
sudo cp /home/webmaster/tenants_back/deploy/tenants_back.env /etc/tenants_back.env
sudo chown root:webmaster /etc/tenants_back.env
sudo chmod 640 /etc/tenants_back.env
# заповни секрети у /etc/tenants_back.env
sudo systemctl daemon-reload
sudo systemctl enable --now tenants_back
```

`gunicorn.service` тримає `RuntimeDirectory=tenants_back` і biнд на
`/run/tenants_back.sock` — у цьому варіанті оновіть `nginx.example.conf`:

```nginx
upstream tenants_back {
    server unix:/run/tenants_back.sock fail_timeout=0;
}
```

Робочий flow апдейтів — той самий, тільки в кінці:

```bash
sudo systemctl reload tenants_back   # graceful HUP
```

---

## 7. Перший bootstrap на чистому сервері

```bash
cd /home/webmaster/tenants_back
sudo -u webmaster .env/bin/python manage.py migrate_schemas --shared
sudo -u webmaster .env/bin/python manage.py collectstatic --noinput
sudo -u webmaster .env/bin/python manage.py bootstrap_public \
  --domain example.com --username root --password 'STRONG'
sudo -u webmaster .env/bin/python manage.py bootstrap_tenant \
  --schema alpha --name "Alpha"  --domain alpha.example.com \
  --admin-username admin --admin-password 'STRONG'
```

---

## 8. Часті граблі

| Симптом                                     | Причина                                     | Як виправити                                                                                  |
|---------------------------------------------|---------------------------------------------|-----------------------------------------------------------------------------------------------|
| nginx → `502 Bad Gateway`                   | nginx не може прочитати сокет                | `sudo usermod -aG www-data webmaster`; впевнитись що `--group=www-data --umask=007` стоять    |
| `Permission denied` на сокеті при старті    | теки `run/` нема або не та власність         | `install -d -o webmaster -g www-data -m 750 /home/webmaster/tenants_back/run`                  |
| `DisallowedHost` у логах                    | `DJANGO_ALLOWED_HOSTS` без потрібного host'а | додати `.example.com` (з крапкою → wildcard)                                                  |
| Свіжий код — старі воркери                  | gunicorn форкнувся при старті                | `sudo supervisorctl restart tenants_back` (для systemd: `systemctl reload`)                   |
| `/static/` 404                              | забули `collectstatic`                       | `manage.py collectstatic --noinput`                                                            |
| Admin: `CSRF verification failed`           | за TLS-проксі, Django про це не знає         | `DJANGO_BEHIND_TLS_PROXY=1` + `DJANGO_CSRF_TRUSTED_ORIGINS=https://*.example.com`              |
| `502` лише на сабдоменах                    | nginx не передає `Host`                      | `proxy_set_header Host $host;` (вже у шаблоні)                                                |
| `Connection refused` до сокета              | сервіс не стартував                          | `tail /var/log/supervisor/tenants_back.log` (або `journalctl -u tenants_back -n 50`)          |
