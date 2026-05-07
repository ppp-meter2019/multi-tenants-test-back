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

Це **єдине місце для прод-overrides** (SECRET_KEY, ALLOWED_HOSTS, CSRF,
CORS, DB-креди, тощо). У репозиторії лежить шаблон
`tenants_back/settings_local.py.example` — копіюй і редагуй:

```bash
cp tenants_back/settings_local.py.example tenants_back/settings_local.py
```

Сам `settings_local.py` гітом не трекаємо — додай у `.gitignore`:
```
tenants_back/tenants_back/settings_local.py
```

Для дев-локалі можеш покласти простіше:
```python
DEBUG = True
ALLOWED_HOSTS = ["*"]
```

Bash-скрипт `bin/gunicorn_start.sh` прод-значень не містить —
експортує тільки `DJANGO_SETTINGS_MODULE` і `PYTHONPATH`. Уся
конфігурація додатка йде через `settings_local.py`.

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

## 8. Як працює ізоляція юзерів між схемами

Чому `tenant_admin` фізично неможливо залогінити на `alpha.localhost`, і
навпаки — `admin@alpha` на `localhost`? Це не магія в коді — це наслідок
того, як `django-tenants` мапить моделі на PostgreSQL schemas плюс як
Postgres резолвить `search_path`.

### 8.1 Один app у двох списках → дві фізичні таблиці

`tenants_back/settings.py` тримає `users` одночасно в `SHARED_APPS` і в
`TENANT_APPS`. `django-tenants` обробляє це так:

| Список                  | На який schema мігрує                              |
|-------------------------|----------------------------------------------------|
| тільки `SHARED_APPS`    | `public` (`migrate_schemas --shared`)              |
| тільки `TENANT_APPS`    | кожна тенантна схема (`alpha`, `beta`, ...)        |
| **в обох**              | **і в `public`, і в кожній тенантній** (документовано) |

Тому після bootstrap у БД фізично існують:
`public.users_user`, `alpha.users_user`, `beta.users_user`,
`gamma.users_user` — це **різні таблиці** з власними `id`-послідовностями
і власними рядками.

### 8.2 Як `search_path` маршрутизує SQL

`TenantMainMiddleware` бере `Host`-заголовок, знаходить запис у
`tenants.Domain` і виконує:

```sql
SET search_path TO <schema>, public;
```

Postgres, отримавши неква­ліфіковане ім'я таблиці `users_user`, іде по
`search_path` зліва направо і **на першому збігу зупиняється**:

- Запит на `alpha.localhost` → `search_path = alpha, public`
  - Таблиця `users_user` існує в `alpha` (бо `users` у `TENANT_APPS`) →
    SQL виконується проти `alpha.users_user`. До `public.users_user`
    черга не доходить.
- Запит на `localhost` → `search_path = public`
  - Виконується проти `public.users_user`.

**Ключове**: `search_path` резолвить **наявність таблиці**, не вміст
рядків. Якщо в `alpha` вже є `users_user` (нехай навіть порожня) —
запити з alpha-контексту НЕ «прошмигнуть» далі до `public.users_user`.
Це не fallback по рядках, а резолвинг імені таблиці.

### 8.3 Куди фізично потрапляють користувачі

`tenants/management/commands/bootstrap_public.py` запускається на public
schema (default для `manage.py`):

```python
User.objects.create_user(username="root", role=Role.TENANT_ADMIN, ...)
# → INSERT into public.users_user
```

`tenants/management/commands/bootstrap_tenant.py` явно перемикає схему:

```python
with schema_context(schema):                # search_path = 'alpha, public'
    User.objects.create_user(username="admin", role=Role.COMPANY_ADMIN, ...)
# → INSERT into alpha.users_user (НЕ public.users_user)
```

Результат: `root` існує **лише** як рядок у `public.users_user`,
`admin@alpha` — лише в `alpha.users_user`.

### 8.4 Що відбувається при спробі залогінитись «не туди»

Сценарій: `root/rootpass` живе в public, користувач шле POST на
`https://alpha.localhost:8000/api/auth/login/`.

1. `TenantMainMiddleware` бачить `Host: alpha.localhost` → `SET search_path TO alpha, public`.
2. URL conf — `urls_tenant.py` → `TenantTokenObtainPairView`.
3. SimpleJWT викликає `authenticate(username="root", password="rootpass")`.
4. ORM компілює `User.objects.get(username="root")` у:
   ```sql
   SELECT id, username, password, role, ... FROM users_user WHERE username='root';
   ```
5. Postgres резолвить `users_user` → `alpha.users_user`. Рядка з
   `username='root'` там немає → `User.DoesNotExist` → backend повертає `None`.
6. SimpleJWT віддає `401 No active account found`.

Запит падає **ще до перевірок ролі** в
`TenantTokenObtainPairSerializer.validate()`. Серіалайзер залишається як
друга лінія оборони — на випадок, якщо хтось випадково створить юзера в
обох схемах, він додатково відхилить за роллю/`connection.schema_name`.

### 8.5 Перевірити «руками»

Підключися `psql tenants_back` і запусти:

```sql
-- 1. Таблиця існує в КОЖНІЙ схемі окремо:
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name = 'users_user'
ORDER BY table_schema;
-- очікуєш: alpha, beta, gamma, public

-- 2. У public сидить тільки tenant_admin:
SET search_path TO public;
SELECT id, username, role FROM users_user;

-- 3. В alpha — інші юзери, root тут НЕ існує:
SET search_path TO alpha, public;
SELECT id, username, role FROM users_user;

-- 4. Доказ що search_path не «перетікає» у public по рядках:
SET search_path TO alpha, public;
SELECT count(*) FROM users_user WHERE username = 'root';
-- → 0  (хоча в public.users_user рядок є)

-- 5. А якщо явно вказати схему — public-копію видно:
SELECT username FROM public.users_user WHERE username = 'root';
-- → root
```

### 8.6 Підводні камені, на які цей патерн НЕ страхує

1. **Однаковий `username` у двох схемах** — валідно. `root@public` і
   `root@alpha` — різні люди з різними паролями. Унікальність — лише
   per-schema (це фіча, не баг).
2. **`id`-простори різні** — `User(id=1)` у public ≠ `User(id=1)` у alpha.
   Не передавай user_id між схемами.
3. **Якщо забути `users` у `TENANT_APPS`** — у тенантних схемах
   `users_user` не створиться, search_path провалиться у public, і всі
   тенанти почнуть юзати **спільну** public-таблицю. Класична помилка
   django-tenants → користувачі «телепортуються» між тенантами.
4. **`schema_context(...)` обов'язковий** для скриптів, які створюють
   tenant-юзерів поза HTTP-запитом — без нього INSERT піде в public.

---

## 9. Міграції в django-tenants — мінігайд

### 9.1 Що важливо розуміти спочатку

`makemigrations` працює на рівні Django — він не знає нічого про
SHARED/TENANT-розділення. Команда генерує **один набір файлів міграцій
на app**, незалежно від того, у яких списках цей app знаходиться.

Те, **на яку схему** конкретна міграція накотиться — вирішує
`migrate_schemas`, спираючись на `SHARED_APPS` / `TENANT_APPS`:

| App у      | `migrate_schemas --shared` | `migrate_schemas --tenant` |
|------------|----------------------------|----------------------------|
| SHARED     | ✅ накатує в `public`       | пропускає                  |
| TENANT     | пропускає                  | ✅ накатує в кожен тенант   |
| BOTH       | ✅ накатує в `public`       | ✅ накатує в кожен тенант   |

При «BOTH» **той самий міграційний файл** виконується двічі: один раз
із `search_path=public` (створюючи `public.users_user`), і потім по
разу для кожного тенанта (створюючи `alpha.users_user`,
`beta.users_user`, ...).

### 9.2 Команди — шпаргалка

| Команда                                            | Що робить                                          |
|----------------------------------------------------|----------------------------------------------------|
| `makemigrations`                                   | Сканує всі `INSTALLED_APPS`, створює файли там, де моделі змінилися |
| `makemigrations <app>`                             | Те саме, але обмежено одним app-ом                 |
| `migrate_schemas`                                  | Накатує **усі** міграції на public + усі тенанти   |
| `migrate_schemas --shared`                         | Лише `public` (тільки apps зі SHARED_APPS)         |
| `migrate_schemas --tenant`                         | Усі тенанти (тільки apps з TENANT_APPS)            |
| `migrate_schemas --schema=alpha`                   | Лише схема `alpha`                                 |
| `migrate_schemas --executor=multiprocessing`       | Те саме, але паралельно (ефект на 10+ тенантах)    |
| `Tenant(auto_create_schema=True).save()`           | Автоматично робить `migrate_schemas --schema=<new>` |

### 9.3 Розгортання з нуля

```bash
# 1. Згенерувати файли міграцій. Для свіжого проекту — безаргументний
#    варіант: Django сам пройде по всіх INSTALLED_APPS і створить
#    0001_initial.py для кожного app-у з моделями.
python manage.py makemigrations

# 2. Накатити SHARED_APPS-міграції в public:
#    створиться public.tenants_*, public.auth_*, public.users_user, ...
python manage.py migrate_schemas --shared

# 3. Створити public-tenant + його domain + tenant-admin:
python manage.py bootstrap_public --domain example.com --username root --password '...'

# 4. Створити кожен тенант. Тут НЕ треба окремого migrate_schemas —
#    Tenant(auto_create_schema=True).save() сам викличе migrate_schemas
#    --schema=<new> для нової схеми. Тобто tenant-таблиці створюються
#    усередині bootstrap_tenant.
python manage.py bootstrap_tenant --schema alpha --domain alpha.example.com ...
python manage.py bootstrap_tenant --schema beta  --domain beta.example.com  ...
```

### 9.4 Внесення змін у існуючий проект

Алгоритм один і той самий для всіх трьох випадків — змінюється лише
**куди** треба накотити після `makemigrations`:

```bash
python manage.py makemigrations <app>
python manage.py sqlmigrate <app> <NNNN_xxx>      # переглянь SQL очима
# далі — залежно від розміщення app у списках:
```

#### A. App тільки в `SHARED_APPS` (наприклад, `tenants`)

Зміна моделі `Tenant`/`Domain` стосується лише public-схеми.

```bash
python manage.py makemigrations tenants
python manage.py migrate_schemas --shared
```

Тенантні схеми не мають цих таблиць, нічого більше робити не треба.

#### B. App тільки в `TENANT_APPS` (наприклад, `cars`, `orders`)

Зміна моделі `Car`/`Order` стосується кожного тенанта. У public цих
таблиць немає.

```bash
python manage.py makemigrations cars
# (для тесту на одному тенанті)
python manage.py migrate_schemas --schema=alpha
# після підтвердження — на всіх:
python manage.py migrate_schemas --tenant
```

#### C. App у **обох** списках (`users`)

Один і той самий міграційний файл треба накотити і на public (там
`tenant_admin`), і на всі тенанти (там `company_admin`/`customer`/`driver`).
Найшвидше — `migrate_schemas` без прапорів:

```bash
python manage.py makemigrations users
python manage.py migrate_schemas
# = --shared + --tenant в один прохід
```

#### D. PR зачіпає одразу всі три типи (типовий випадок)

Уявимо що один PR змінює: `Tenant.is_active` (SHARED-only), `Car.color`
(TENANT-only) і `User.phone` (BOTH).

```bash
python manage.py makemigrations          # створить три файли міграцій
python manage.py migrate_schemas         # один прохід — кожна схема отримає своє
```

`migrate_schemas` без прапорів сам розбереться:

| Схема         | Які з трьох міграцій застосуються                         |
|---------------|-----------------------------------------------------------|
| `public`      | `tenants` (бо в SHARED) + `users` (бо у BOTH) — **2 з 3** |
| `alpha`       | `cars` (бо в TENANT) + `users` (бо у BOTH) — **2 з 3**    |
| `beta`        | те саме що в alpha                                         |
| `gamma`       | те саме                                                    |

Кожна схема має свою таблицю `django_migrations` → нічого не накотиться
двічі і нічого не пропуститься. Повторний запуск `migrate_schemas` —
no-op.

> **Захисний дефолт деплою**: якщо не впевнений, який саме app зачепили
> зміни — виконуй `migrate_schemas` (без прапорів). Він безпечно прокотить
> усе непокатане у всіх схемах. Прапори (`--shared`, `--tenant`,
> `--schema=`) потрібні лише коли треба зробити частину (наприклад,
> протестити на одному тенанті перед розкочуванням на всі).

### 9.5 Чи може структура **однієї таблиці** відрізнятись?

#### Між `public.users_user` і `alpha.users_user` (одна таблиця, два розміщення)

**Ні.** Файл `users/migrations/0001_initial.py` (та всі наступні) — один,
накочується ідентично і на public, і на кожен тенант. Колонки,
constraints, indexes — однакові у `public.users_user`,
`alpha.users_user`, `beta.users_user`. Різняться лише **рядки даних** і
значення `id`-послідовностей.

Якщо потрібна різниця в **поведінці** (а не в схемі), використовуй
рантайм-логіку в коді:
- `if connection.schema_name == "public": ...`
- різні `Manager`-и
- `JSONField` для гнучких per-tenant атрибутів.

#### Між `alpha.cars_car` і `beta.cars_car` (різні тенанти)

**Ні** в коректному стані системи. `migrate_schemas --tenant` накатує
**однакову** послідовність міграцій на кожен тенант → структура у всіх
тенантів ідентична.

Розбіжність може виникнути лише як **bug**:
- `migrate_schemas --schema=alpha` зробили, а на beta забули → beta «застрягне» на старішій версії схеми.
- Міграція впала посередині на одному з тенантів.
- Тенант відновлювали з бекапу старшого, ніж поточний код.

Усе це симптоми того, що тенанти розсинхронізувалися. Лікується через
`migrate_schemas --tenant` (накотить пропущене на всіх) або
`migrate_schemas --schema=<імʼя>` для конкретного відстаючого.

`django-tenants` не має офіційного механізму «у тенанта alpha поле X, а
у beta поле Y» — це йшло б проти моделі мульти-тенантності тут.
Кастомні per-tenant атрибути роби або через `JSONField`, або через
окремі моделі-«profile», прив'язані до тенанта.

### 9.6 Підводні камені

1. **`makemigrations` vs `makemigrations <app>` — результат ідентичний.**
   Django у обох випадках сканує `INSTALLED_APPS` і генерує файли тільки
   для app-ів, де реально змінилися моделі. Який варіант писати —
   залежить від ситуації:
   - **Свіжий проект / перший раз** → `makemigrations` без аргументів.
     Канонічно: тобі потрібен `0001_initial.py` для всіх app-ів одразу.
   - **Точкова зміна в існуючому проекті** → краще `makemigrations <app>`.
     Це декларація явного наміру (у коміті/PR видно, що зачеплено саме
     `cars`, а не «щось»), плюс захист від випадковостей: якщо у
     сусідньому app-і лежать незакомічені зміни моделей з іншої гілки,
     безаргументний `makemigrations` тихо бахне файл і там — і ти можеш
     закомітити «бонусну» міграцію.
2. **Імпорт моделей у міграціях** — у `RunPython`-функціях бери
   `apps.get_model("app", "Model")`, не імпортуй прямо. Інакше якщо
   модель потім зміниться, історична міграція впаде.
3. **Дані в `RunPython`-міграціях для apps в обох списках** — функція
   виконається і на public, і на кожному тенанті. Якщо логіка має
   різнитися, всередині перевіряй `connection.schema_name`.
4. **FK з тенантного app на public-only модель** — працює (search_path
   падає в public для відсутньої таблиці). Але FK з public-only моделі
   на тенантну — НЕ працює: public не має тенантних таблиць, і Postgres
   не зрозуміє, на яку фізичну таблицю посилатися.
5. **Перейменування app, що в обох списках** — потребує синхронної
   зміни в обох списках і перевірки що `django_migrations` (per-schema)
   має правильний `app`-label у вже застосованих рядках. Зазвичай
   простіше створити новий app + data-migration ніж rename.
6. **Squashing міграцій** — squashed-міграції теж пройдуть і на public,
   і на тенантах. Обережно з `RunPython`-стейтами в проміжних кроках,
   які залежали від наявності проміжних колонок.

### 9.7 Робочий чекліст для деплою змін

```bash
# 1. (на dev) згенерував міграцію
python manage.py makemigrations <app>
python manage.py sqlmigrate <app> <NNNN>     # переглянь SQL очима

# 2. локально прокатав на одному тенанті
python manage.py migrate_schemas --schema=alpha

# 3. протестив; запушив код у git, deploy

# 4. на проді (під webmaster):
sudo -u webmaster .env/bin/python manage.py migrate_schemas
# → один прохід, public + усі тенанти підтягнуть нові міграції

# 5. graceful restart воркерів:
sudo supervisorctl restart tenants_back
```

---

## 10. Створення нового тенанта в існуючій системі

`bootstrap_tenant` зручний для першого розгортання, але в живому проді
тенанти зазвичай додаються одним із трьох шляхів. У всіх трьох є
*спільний підводний камінь*: створення `Tenant` + `Domain` ще НЕ створює
користувачів усередині нової схеми. Перший `company_admin` потрібно
доробити окремо — інакше `https://delta.example.com/admin/` пустить нікого.

### 10.1 Через Django admin на public-сайті

1. Login на `https://example.com/admin/` як `tenant_admin` (`root`).
2. **Tenants → Add Tenant**. Заповнити `name` (наприклад «Delta») і
   `schema_name` (`delta`). Save.
   - `Tenant.save()` через `auto_create_schema=True` запускає
     `migrate_schemas --schema=delta` → схема створюється і всі
     TENANT_APPS-міграції накатуються автоматично.
3. **Domains → Add Domain**. Заповнити `domain` (`delta.example.com`),
   обрати `tenant=Delta`, поставити `is_primary=True`. Save.
4. *Перевірити DNS*: `delta.example.com` має резолвитися на ваш сервер
   (wildcard A-запис на `*.example.com` уже покриє це).
5. **Створити першого company_admin** — див. §10.4.

### 10.2 Через REST API

Як `tenant_admin` із валідним JWT:

```bash
TA=$(curl -s -X POST https://example.com:8000/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"..."}' | jq -r '.access')

curl -X POST https://example.com:8000/api/tenants/ \
  -H "Authorization: Bearer $TA" \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_name": "delta",
    "name": "Delta",
    "domain": "delta.example.com"
  }'
```

`TenantSerializer.create()` атомарно створює `Tenant` + `Domain` →
`auto_create_schema=True` робить решту. Той самий gap із company_admin —
див. §10.4.

### 10.3 Через ORM у `manage.py shell`

Найпряміший шлях — в одній сесії можна одразу й company_admin зробити:

```python
from tenants.models import Tenant, Domain
from users.models import User
from django_tenants.utils import schema_context

t = Tenant.objects.create(schema_name="delta", name="Delta")
Domain.objects.create(tenant=t, domain="delta.example.com", is_primary=True)

with schema_context("delta"):
    User.objects.create_user(
        username="admin",
        password="strongpass",
        role=User.Role.COMPANY_ADMIN,
        is_staff=True,
        is_superuser=True,
    )
```

### 10.4 Як добити перший `company_admin` після створення (§10.1 / §10.2)

Найпростіше — повторно запустити `bootstrap_tenant`. Команда
**ідемпотентна**: `Tenant`/`Domain` пропустить (бо вже є), а юзера
створить:

```bash
sudo -u webmaster .env/bin/python manage.py bootstrap_tenant \
  --schema delta --name "Delta" --domain delta.example.com \
  --admin-username admin --admin-password 'STRONG_PASS'
```

Альтернативи:

```bash
# через django-tenants tenant_command — викликає будь-яку management-
# команду в контексті конкретної схеми
sudo -u webmaster .env/bin/python manage.py tenant_command shell --schema=delta
# у shell:
>>> from users.models import User
>>> User.objects.create_user(username="admin", password="...",
...     role=User.Role.COMPANY_ADMIN, is_staff=True, is_superuser=True)
```

`tenant_command createsuperuser --schema=delta` теж працює, але створить
юзера з дефолтною роллю `customer` — після цього треба зайти у admin
тенанта і виставити `role=company_admin`. Простіше використати
`bootstrap_tenant`.

### 10.5 Як видалити тенант

`Tenant.auto_drop_schema = True` (вже виставлено у моделі) робить так,
що `Tenant.delete()` фізично дропає схему з усіма таблицями. Через
admin: вибрати тенант → Delete. Або:

```python
Tenant.objects.get(schema_name="delta").delete()   # → DROP SCHEMA delta CASCADE
```

⚠️ Це **незворотньо** — даних після цього не повернеш окрім як з бекапа БД.

---

## 11. API surface

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

## 12. Валідації (вбудовано в моделі/серіалайзери)

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

## 13. Quick smoke test (curl)

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

## 14. Production deployment

Окремий гайд: [`deploy/README.md`](deploy/README.md). Коротко:

- **Запуск gunicorn** — bash-скрипт `bin/gunicorn_start.sh` (зручно під
  supervisor). Скрипт займається тільки рантаймом (venv, сокет, воркери);
  усі прод-overrides — у `tenants_back/settings_local.py` (копія з
  `settings_local.py.example`).
- **nginx** — шаблон `deploy/nginx.example.conf` (два `server { }`-блоки:
  `:443` віддає SPA + admin, `:8000` публікує API; обидва проксують у
  той самий gunicorn-сокет).
- **systemd** як альтернатива supervisor — теж описано в `deploy/README.md`.

---

## 15. Project layout

```
tenants_back/
├── manage.py
├── requirements.txt
├── README.md
├── bin/
│   └── gunicorn_start.sh                # supervisor-friendly launcher (runtime only)
├── deploy/
│   ├── README.md                        # повний прод-гайд
│   ├── nginx.example.conf               # nginx vhost (:443 SPA + :8000 API)
│   ├── gunicorn.conf.py                 # альтернатива bin-скрипту (для systemd)
│   └── gunicorn.service                 # systemd-юніт
├── tenants_back/                        # project package
│   ├── settings.py
│   ├── settings_local.py.example        # шаблон прод-overrides
│   ├── settings_local.py                # gitignored, реальні значення
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
