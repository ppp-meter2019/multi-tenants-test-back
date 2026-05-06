# tenants_back — multi-tenant Django/DRF demo

Multi-tenant SaaS skeleton built with **Django 5**, **Django REST Framework**,
**django-tenants** (PostgreSQL schemas), **djangorestframework-simplejwt** і
`django-cors-headers` (для дев split-origin із фронтом).

Кожна компанія (Alpha / Beta / Gamma / ...) — окремий тенант із власною
PostgreSQL-схемою. Drivers, customers, cars, products, orders і routes
ізольовані per-tenant. Tenant-адміни живуть у public-схемі та керують
списком тенантів.

Фронтенд — у сусідній теці `../tenants_front/` (vanilla JS, ES-модулі).
Прод-розгортання — `deploy/README.md`.

---

## 1. Requirements

- Python 3.10+
- PostgreSQL 13+ (django-tenants потребує підтримки схем — SQLite не підійде)
- venv `p_env` із чекаута, або свіжий

```bash
source ../p_env/bin/activate           # або: python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Database

```sql
CREATE USER postgres WITH SUPERUSER PASSWORD 'postgres';
CREATE DATABASE tenants_back OWNER postgres;
```

Креденшіали можна перевизначити env-змінними (`DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST`, `DB_PORT`) — за замовчуванням
`postgres / postgres @ 127.0.0.1:5432`.

## 3. Hosts file (тільки для дев)

Multi-tenancy керується hostname'ом. У `/etc/hosts`:

```
127.0.0.1   localhost alpha.localhost beta.localhost gamma.localhost
```

## 4. Локальні налаштування — `settings_local.py`

`tenants_back/settings.py` у самому кінці робить:

```python
try:
    from .settings_local import *  # noqa: F403
except ImportError:
    print("Can't load local settings!")
```

Файл `tenants_back/settings_local.py` **не комітимо**; це місце для
особистих оверрайдів — можеш покласти, наприклад:

```python
# tenants_back/settings_local.py  (gitignored)
DEBUG = True
DATABASES["default"]["NAME"] = "tenants_back_dev"
ALLOWED_HOSTS = ["*"]
```

Якщо тримати його порожнім — `print("Can't load local settings!")` нагадає,
що файлу немає (це нормально для першого запуску; додай порожній файл, якщо
повідомлення дратує).

## 5. First-time setup

```bash
# Згенерувати міграції для всіх app-ів
python manage.py makemigrations tenants users customers drivers cars products orders routes

# Накатити SHARED_APPS-міграції в public-схему (Tenant, Domain, User on public)
python manage.py migrate_schemas --shared

# Створити public-tenant + tenant-admin
python manage.py bootstrap_public --domain localhost --username root --password rootpass

# Створити три тенанти, кожен зі своєю схемою + company-admin
python manage.py bootstrap_tenant --schema alpha --name "Alpha LLC"  --domain alpha.localhost --admin-username admin --admin-password adminpass
python manage.py bootstrap_tenant --schema beta  --name "Beta LLC"   --domain beta.localhost  --admin-username admin --admin-password adminpass
python manage.py bootstrap_tenant --schema gamma --name "Gamma LLC"  --domain gamma.localhost --admin-username admin --admin-password adminpass
```

`bootstrap_tenant` викликає `migrate_schemas` для нової схеми через
`Tenant(auto_create_schema=True)`.

Запуск дев-сервера:

```bash
python manage.py runserver
```

---

## 6. Hostname → URL conf mapping

| Host                | URL conf                              | Призначення              |
|---------------------|---------------------------------------|--------------------------|
| `localhost`         | `tenants_back.urls_public`            | Керування тенантами      |
| `alpha.localhost`   | `tenants_back.urls_tenant`            | Бізнес-API alpha         |
| `beta.localhost`    | `tenants_back.urls_tenant`            | Бізнес-API beta          |
| `gamma.localhost`   | `tenants_back.urls_tenant`            | Бізнес-API gamma         |

`TenantMainMiddleware` перемикає PostgreSQL `search_path` за hostname'ом
ще до того, як хоч один view торкнеться БД.

---

## 7. Roles

| Роль             | Де живе       | Де логіниться             | Що може                                |
|------------------|---------------|---------------------------|----------------------------------------|
| `tenant_admin`   | `public`      | `localhost`               | CRUD тенантів; Django admin на public  |
| `company_admin`  | tenant schema | `<tenant>.localhost`      | Повний CRUD сутностей + Django admin   |
| `customer`       | tenant schema | `<tenant>.localhost`      | Каталог + замовлення                   |
| `driver`         | tenant schema | `<tenant>.localhost`      | Призначені маршрути (read-only)        |

У кожній схемі — своя таблиця `auth_user`, тож унікальність username'у —
лише в межах одного тенанта (`admin` у alpha й `admin` у beta — різні акаунти).

---

## 8. API surface

### Public host (`http://localhost:8000`)

- `POST /api/auth/login/` — `{ "username": ..., "password": ... }` → JWT (access+refresh).
- `POST /api/auth/refresh/`
- `GET / POST /api/tenants/`, `PATCH/DELETE /api/tenants/<id>/`
- `GET /admin/` — Django admin (Tenant, Domain, User у public).

### Tenant host (`http://alpha.localhost:8000`)

- `POST /api/auth/login/` (відхиляє `tenant_admin`)
- `POST /api/auth/refresh/`
- `/api/cars/` — лише admin
- `/api/drivers/` — лише admin; плоска форма: `username`, `password`, `first_name`, `last_name`, `date_of_birth`, `license_number`
- `/api/customers/` — лише admin; `GET/PATCH /api/customers/me/` — для самого клієнта
- `/api/products/` — admin пише, будь-який автентифікований читає
- `/api/orders/` — admin бачить усе, customer — тільки своє
- `/api/routes/` — admin керує, driver/customer читають що їх стосується
- `/admin/` — Django admin для тенанта

### JWT payload

Access-токени містять claims `role`, `schema`, `username`. Передавати
`Authorization: Bearer <token>`.

---

## 9. Валідації (вбудовано в моделі/серіалайзери)

- `Car.license_plate` — унікальний, regex `[A-Z0-9\- ]{4,16}`, нормалізація в upper-case.
- `Car.year` — 1900..(поточний рік + 1).
- `Driver.license_number` — унікальний, regex `[A-Z0-9\-]{4,32}`, upper-case.
- `Driver.date_of_birth` — не в майбутньому; мін. вік 18.
- `User.username` — унікальний per-schema (стандартно для Django).
- `Customer.phone` — optional, м'який regex.
- `Order` — мусить мати ≥1 позицію; один продукт не повторюється.
- `Route` — той самий driver/car не буває на двох одночасно активних/запланованих маршрутах.
- Зміна статусу маршруту (`active` / `completed`) синхронно перекидає статуси прив'язаних замовлень у `in_route` / `delivered`.

---

## 10. Quick smoke test (curl)

```bash
# 1. Tenant-admin login на public
TA=$(curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"rootpass"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access"])')

# 2. Список тенантів
curl -s http://localhost:8000/api/tenants/ -H "Authorization: Bearer $TA"

# 3. Company-admin login на alpha
AA=$(curl -s -X POST http://alpha.localhost:8000/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"adminpass"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access"])')

# 4. Машина
curl -s -X POST http://alpha.localhost:8000/api/cars/ \
  -H "Authorization: Bearer $AA" -H 'Content-Type: application/json' \
  -d '{"brand":"Volvo","model":"FH","year":2022,"license_plate":"AA 1234 BB"}'

# 5. Водій
curl -s -X POST http://alpha.localhost:8000/api/drivers/ \
  -H "Authorization: Bearer $AA" -H 'Content-Type: application/json' \
  -d '{"username":"john","password":"strongpass1","first_name":"John","last_name":"Doe","date_of_birth":"1990-05-12","license_number":"UA-12345"}'

# 6. Товар
curl -s -X POST http://alpha.localhost:8000/api/products/ \
  -H "Authorization: Bearer $AA" -H 'Content-Type: application/json' \
  -d '{"name":"Widget","price":"19.99"}'
```

---

## 11. Production deployment

Окремий гайд: [`deploy/README.md`](deploy/README.md). Коротко:

- **Запуск gunicorn** — bash-скрипт `bin/gunicorn_start.sh` (зручно під
  supervisor). Усі прод env-змінні (`DJANGO_*`, `DB_*`) — inline `export` у
  скрипті.
- **nginx** — шаблон `deploy/nginx.example.conf` (один `server { }` ловить
  apex + wildcard сабдомени, проксує `/api/` і `/admin/` у gunicorn-сокет,
  усе інше — SPA з `tenants_front/`).
- **systemd** як альтернатива supervisor — теж описано в `deploy/README.md`.

---

## 12. Project layout

```
tenants_back/
├── manage.py
├── requirements.txt
├── README.md
├── bin/
│   └── gunicorn_start.sh         # supervisor-friendly launcher (inline env)
├── deploy/
│   ├── README.md                 # повний прод-гайд
│   ├── nginx.example.conf        # nginx vhost (apex + *.example.com)
│   ├── gunicorn.conf.py          # альтернатива bin-скрипту (для systemd)
│   ├── gunicorn.service          # systemd-юніт
│   └── tenants_back.env          # шаблон env-файлу (тільки для systemd-варіанту)
├── tenants_back/                 # project package
│   ├── settings.py
│   ├── settings_local.py         # gitignored, локальні оверрайди
│   ├── urls_public.py
│   ├── urls_tenant.py
│   └── wsgi.py
├── tenants/                      # SHARED — Tenant, Domain, public AdminSite, bootstrap-команди
├── users/                        # SHARED + TENANT — custom User, JWT, permissions
├── customers/
├── drivers/
├── cars/
├── products/
├── orders/
└── routes/
```
