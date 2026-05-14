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

## 0. HIPAA та архітектурний вибір (фактологічна довідка)

Розділ адресує часте питання: «чи можна на schema-per-tenant архітектурі
(як у цьому проекті) обслуговувати клієнтів, що працюють з PHI під
HIPAA?». Це довідкова інформація з посиланнями на першоджерела —
не юридична порада.

### 0.1 Що HIPAA фактично вимагає

HIPAA — це **Health Insurance Portability and Accountability Act of
1996** (Public Law 104-191). Технічні вимоги до зберігання й обробки
PHI (Protected Health Information) сидять у **HIPAA Security Rule**,
кодифікованому як **45 CFR §§164.302–164.318**.

Релевантні параграфи **Security Rule** (45 CFR Part 164, **Subpart C**):

| §                  | Що регулює                                              | Релевантне до multi-tenant архітектури                                  |
|--------------------|----------------------------------------------------------|--------------------------------------------------------------------------|
| §164.306(a)        | Загальні вимоги до covered entities/business associates  | Зобов'язує забезпечити конфіденційність, цілісність і доступність e-PHI |
| §164.306(b)(1)     | Flexibility of approach                                  | «Reasonable and appropriate» — підхід обирається з огляду на розмір/складність організації, її можливості, вартість заходів, ймовірність ризиків |
| §164.308           | Administrative safeguards                                | Управління ризиками, тренінг персоналу, контракти                       |
| §164.310           | Physical safeguards                                      | Контроль фізичного доступу до серверів                                  |
| §164.312(a)(1)     | Access control                                           | Unique user identification, emergency access, auto-logoff, encryption/decryption |
| §164.312(b)        | Audit controls                                           | Hardware/software mechanisms що записують активність із PHI            |
| §164.312(c)(1)     | Integrity                                                | Захист e-PHI від несанкціонованих змін                                 |
| §164.312(d)        | Person or entity authentication                          | Підтвердження ідентичності користувача                                  |
| §164.312(e)(1)     | Transmission security                                    | Захист e-PHI під час передачі мережею                                  |
| §164.314(a)        | Organizational requirements / BAA                        | Вимоги до Business Associate Agreement між Covered Entity та сервіс-провайдером |
| §164.316(b)(2)     | Time limit for documentation                              | Зберігати документацію політик і процедур ≥6 років від дати створення / останньої редакції |

Релевантні параграфи **Privacy Rule** (45 CFR Part 164, **Subpart E**) — це окремий підрозділ, який часто змішують із Security Rule, але він регулює дозволи на disclosure PHI, не технічні safeguards:

| §                  | Що регулює                                              | Релевантне до multi-tenant архітектури                                  |
|--------------------|----------------------------------------------------------|--------------------------------------------------------------------------|
| §164.502(e)        | Disclosures to business associates                       | Підстава для існування BAA — Covered Entity має право розкрити PHI BA лише за наявності контракту |
| §164.504(e)        | Business associate contracts                             | Зміст контракту BA: дозволені цілі використання PHI, повідомлення про порушення тощо |

Розділення важливе тому, що §164.502 / §164.504 — це **Privacy Rule**: на них посилаються при обговоренні BAA (як у §0.3.2), але **технологічні вимоги** (encryption, access control, audit) живуть у Security Rule і покриваються §164.312.

### 0.2 Чого HIPAA не вимагає

Security Rule **не містить жодного речення про обов'язкову ізоляцію
тенантів на рівні окремих баз даних**. Підстави:

- §164.306(b)(1) явно проголошує **технологічну нейтральність**:
  covered entities/BA вільні обирати реалізацію, що є «reasonable and
  appropriate» з огляду на розмір/складність організації, технічну
  інфраструктуру, вартість заходів, ймовірність і критичність ризиків.
- §164.312 описує **функціональні** вимоги (access control, audit,
  integrity, authentication, transmission), але **не описує
  архітектурну топологію** даних.
- У **HHS Office for Civil Rights (OCR) Guidance on HIPAA** термінів
  «database per tenant», «schema isolation», «single-tenant database»
  не використовується.
- **NIST SP 800-66 Rev. 2** («Implementing the HIPAA Security Rule») —
  офіційний implementation guide від NIST — рекомендує конкретні
  технічні контролі, але не пропонує і не вимагає DB-per-tenant.

### 0.3 Звідки виникає практика DB-per-tenant у HIPAA-контексті

Хоча буква регуляції цього не вимагає, у healthcare-SaaS склалася
стійка практика, що базується на трьох незалежних факторах.

#### 0.3.1 Вимоги аудиторських фреймворків

OCR — це **enforcement body** HIPAA. Власне HIPAA-сертифікації від OCR
не існує. На практиці підтвердження HIPAA-compliance відбувається через
сторонні фреймворки:

- **HITRUST Common Security Framework (CSF)** — найпоширеніший у
  healthcare SaaS. HITRUST мапить власні контролі на HIPAA Security
  Rule. У CSF присутні контролі, що оцінюють multi-tenant ізоляцію
  (точні номери варіюються між версіями CSF v9/v11 — звіряти із
  чинною версією каталогу контролів):
  - Загальний принцип оцінки: вимагається демонстрація «**logical or
    physical segregation between tenants**».
  - Логічна сегрегація (schema-isolation) приймається, але вимагає
    більшого обсягу evidence: tested role-based grants, code-level
    controls, penetration testing.
  - Фізична сегрегація (DB-per-tenant) приймається з меншою кількістю
    evidence.
  - *Конкретний control ID — звіряй у поточному HITRUST CSF assessment
    guide для своєї versions (v9.x / v11.x).*
- **SOC 2 Type II** (AICPA Trust Services Criteria) — релевантні:
  **CC6.1** («The entity implements logical access security software,
  infrastructure, and architectures over protected information
  assets»), **CC6.3** («The entity authorizes, modifies, or removes
  access to data, software, functions, and other protected information
  assets based on roles, responsibilities, or the system design and
  changes»). Архітектурна простота DB-per-tenant скорочує testing scope
  для обох контролів — окремі credentials і окремий endpoint per
  tenant самі по собі є evidence для CC6.1, а role-based access у
  межах одного tenant'а — для CC6.3.
  *(NB: CC6.6 у TSC — це про zewнішні threats, perimeter security; до
  multi-tenant ізоляції безпосередньо не стосується.)*

#### 0.3.2 Вимоги конкретних BAA з боку Covered Entities

§164.504(e) дає Covered Entities право встановлювати додаткові умови у
BAA. У публічних шаблонах BAA від великих covered entities часто
фігурує формулювання на зразок:

> «Business Associate shall ensure that Covered Entity's Protected
> Health Information is **logically or physically separated** from
> data of other customers...»

Деякі covered entities (особливо великі) у BAA прописують саме
**«physically separated»**, що автоматично виключає schema-per-tenant
як варіант.

#### 0.3.3 Defense-in-depth інтерпретація §164.306(a)(2)

§164.306(a)(2) вимагає захисту від «**any reasonably anticipated
threats or hazards to the security or integrity of such information**».

«Reasonably anticipated» інтерпретується аудиторами як «включаючи
помилки у коді сервіс-провайдера». Defense-in-depth аргумент:

- При DB-per-tenant логічна помилка в маршрутизації запиту все одно не
  дає доступу до іншої БД (фізичний бар'єр у вигляді окремого
  DSN/credentials).
- При schema-per-tenant логічна помилка може призвести до cross-schema
  leak, якщо PG-роль має доступ до інших схем (доступ контролюється
  лише `search_path` + grant'ами).

Цей аргумент **не присутній у тексті §164.306**, але є типовим у risk
assessment, що подаються до auditor'а.

### 0.4 Як schema-per-tenant задовольняє §164.312 з evidence

Schema-per-tenant архітектура задовольняє Security Rule, якщо технічні
контролі покривають усі підпункти §164.312:

| §164.312 підпункт                  | Evidence для schema-per-tenant                                                       |
|------------------------------------|--------------------------------------------------------------------------------------|
| (a)(1) Access control              | Окрема PG-роль для тенанта; `REVOKE ALL ON SCHEMA other_tenant FROM tenant_role`; encryption at rest (AWS KMS, Aurora storage encryption); session timeout |
| (a)(2)(i) Unique user identification | Per-tenant `users_user` таблиця в кожній схемі; JWT із tenant claim                |
| (a)(2)(iii) Automatic logoff       | JWT TTL політика; Django session expiration                                          |
| (a)(2)(iv) Encryption/decryption  | Aurora encryption at rest (AES-256); TLS 1.2+ in transit                              |
| (b) Audit controls                  | `pgaudit` extension (параметри `pgaudit.log = 'read,write,ddl,role'`, `pgaudit.log_relation`) записує DDL/DML; structured app-logs із tenant ID; retention аудит-логів — політика організації. HIPAA **прямо не вимагає** конкретного терміну для audit logs; §164.316(b)(2)(i) задає ≥6 років для **документації політик і процедур**, і за аналогією з нею більшість organizatons зберігають audit logs ≥6 років (це індустріальна практика, не норма Security Rule) |
| (c)(1) Integrity                    | Backup'и (point-in-time recovery в Aurora); checksums; immutable audit log          |
| (c)(2) Mechanism to authenticate e-PHI | Cryptographic hashes/checksums над сенситивними полями; pgaudit DDL/DML-лог як evidence не-альтерованості; signed audit trail |
| (d) Person or entity authentication | Multi-factor authentication; SSO integration (SAML/OIDC); JWT signature verification |
| (e)(1) Transmission security        | TLS для всіх з'єднань (client→nginx, nginx→app, app→Aurora); HSTS                   |
| (e)(2)(i) Integrity controls       | TLS гарантує цілісність                                                              |
| (e)(2)(ii) Encryption (addressable)| TLS 1.2+ обов'язково; AWS PrivateLink для in-VPC                                    |

Додаткові evidence-артефакти, що зазвичай вимагає аудитор:

1. **PG role permissions matrix** — який role може SELECT/INSERT/UPDATE/DELETE у яких схемах.
2. **Penetration test report** — спроба cross-tenant data access.
3. **Code review evidence** — для middleware/routing коду.
4. **Backup/restore drill** — відновлення даних одного тенанта без зачепання інших.
5. **Incident response runbook** — обмеження впливу cross-tenant leak якщо станеться.

Для DB-per-tenant ті самі §164.312 покриваються коротшим evidence: окремі
PG database = окремі credentials = окремий network endpoint;
cross-tenant leak фізично можливий лише при свідомій мутації коду; BAA
формулювання «logically OR physically separated» задовольняється за
визначенням.

### 0.5 Резюме

- **HIPAA Security Rule (45 CFR §§164.302-164.318)** не містить норми,
  що вимагає DB-per-tenant; §164.306(b) explicitly дозволяє будь-який
  «reasonable and appropriate» підхід.
- Практика healthcare-SaaS схиляється до DB-per-tenant через **обсяг
  evidence**, потрібного для HITRUST/SOC 2 аудиту, через
  **формулювання конкретних BAA** від великих covered entities, та
  через **defense-in-depth інтерпретацію §164.306(a)(2)** — не через
  текст самої регуляції.

### 0.6 Першоджерела

- HIPAA Security Rule: 45 CFR Part 164 Subpart C — https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-164/subpart-C
- HIPAA Privacy Rule (BAA-вимоги §502/§504): 45 CFR Part 164 Subpart E — https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-164/subpart-E
- HHS OCR Guidance: https://www.hhs.gov/hipaa/for-professionals/security/guidance/index.html
- NIST SP 800-66 Rev. 2 (Implementing the HIPAA Security Rule): https://csrc.nist.gov/publications/detail/sp/800-66/rev-2/final
- HITRUST CSF: https://hitrustalliance.net/product-tool/hitrust-csf/
- AICPA Trust Services Criteria (SOC 2): https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services

---

## 1. Підхід django-tenants — опис і аналіз сильних сторін у контексті Celery

`django-tenants` реалізує мульти-тенантність на рівні **PostgreSQL schemas**,
а не окремих БД. У такій моделі:

- Один PostgreSQL-кластер містить одну логічну БД (наприклад, `app_main`).
- У цій БД існує `public` schema і N схем тенантів (`alpha`, `beta`, `gamma`, ...).
- Кожна tenant-схема містить **повний набір таблиць**, ідентичних структурно:
  `cars_car`, `orders_order`, `users_user` тощо.
- `public` тримає реєстр тенантів (`tenants_tenant`, `tenants_domain`) + опційно
  shared-моделі.

### 1.1 Ключові компоненти пакета

| Компонент                                          | Призначення                                                                            |
|----------------------------------------------------|----------------------------------------------------------------------------------------|
| `TenantMixin` / `DomainMixin`                      | Базові класи моделей тенанта і домена. `auto_create_schema=True` запускає міграції автоматично при `Tenant.save()`. |
| `django_tenants.postgresql_backend`                | Кастомний DatabaseWrapper, що обгортає `django.db.backends.postgresql` додатковими методами `set_tenant()`, `set_schema()`. |
| `TenantMainMiddleware`                             | За заголовком `Host` знаходить запис у `Domain` і викликає `connection.set_tenant(tenant)`, що транслюється у `SET search_path TO <schema>, public` на рівні PG. |
| `schema_context()` / `tenant_context()`            | Context manager'и для перемикання схеми поза HTTP-запитом (cron-job, management команди, Celery-worker). |
| `migrate_schemas` management command               | Запускає Django міграції для public + кожної тенантської схеми. Підтримує `--shared`, `--tenant`, `--schema=<name>`, `--executor=multiprocessing`. |
| `SHARED_APPS` / `TENANT_APPS` (settings)           | Декларація, які Django-app-и мігрують у public, а які — в кожен tenant. Один app може бути в обох списках. |
| `TenantSyncRouter` (DATABASE_ROUTERS)              | Каже, які моделі куди мігрувати, відповідно до списків.                                |
| `tenant_command` management command                | Обгортка для запуску будь-якої management-команди в контексті конкретної схеми.        |

### 1.2 Як іде HTTP-запит

1. nginx/gunicorn передає запит у Django зі збереженим `Host` (наприклад
   `alpha.example.com`).
2. `TenantMainMiddleware` (перший у `MIDDLEWARE`) робить
   `Domain.objects.select_related("tenant").get(domain="alpha.example.com")`.
3. Викликає `connection.set_tenant(tenant)` → у PG виконується
   `SET search_path TO alpha, public`.
4. Усі наступні ORM-виклики у view'і резолвлять `cars_car` як
   `alpha.cars_car`, бо PostgreSQL шукає таблиці по `search_path` зліва направо.
5. Після виконання view'у відповідь повертається; на наступному запиті
   middleware виставить інший `search_path`. Connection повертається до
   пулу/тримається persistent.

### 1.3 Як іде міграція

```
makemigrations            → генерує файли для всіх app-ів
migrate_schemas --shared  → public: накатує лише SHARED_APPS
migrate_schemas --tenant  → для кожної tenant-схеми накатує TENANT_APPS
migrate_schemas           → робить обидва за один прохід
```

`auto_create_schema=True` на `Tenant`-моделі викликає
`migrate_schemas --schema=<new>` синхронно під час `Tenant.save()` — нова
схема готова до використання в момент завершення INSERT'у.

### 1.4 Connection economics: лінійне зростання по воркерах, не по тенантах

Зміна tenant'а на одному connection'і — це **одна SQL-команда**
`SET search_path TO X, public`, виконання якої займає мікросекунди.
Connection при цьому **не закривається**, не передоговорює TLS,
не re-auth'иться.

Конкретно для прод-сценарію зі 100 gunicorn-воркерами і 1000 тенантами:

- Кожен воркер тримає persistent connection (`CONN_MAX_AGE > 0`)
- Один connection обслуговує запити до будь-якого тенанта
- **Загалом 100 connection'ів до PG**, незалежно від кількості тенантів

Альтернативна архітектура (DB-per-tenant) у тому самому сценарії
потребувала б connection pool на кожну з 1000 БД, мультиплексованих через
PgBouncer у transaction-mode — це сотні-тисячі backend-connection'ів плюс
операційна складність пулера.

### 1.5 Уніфіковане операційне дерево

- **Один backup-target**: для dev/clone-сценаріїв і per-schema-restore — `pg_dump app_main`, відновлення одного тенанта `pg_restore --schema=alpha`. Для prod-Aurora `pg_dump` на cluster з 1+ TB йде годинами, конкурує за I/O credits із live-трафіком — канонічний backup тут це **continuous backup + PITR** (Aurora storage-level snapshot до S3, restore через `RestoreDBClusterToPointInTime`). pg_dump лишається корисним як інструмент **per-tenant export**, не як основний backup mechanism.
- **Один моніторинг-target**: `pg_stat_activity`, `pg_stat_statements`,
  `pg_stat_user_tables` показують єдину картину навантаження.
- **Один failover**: при Aurora failover'і всі тенанти переключаються разом,
  без per-tenant координації.
- **Один TLS-сертифікат, один pg_hba**: одна точка налаштування auth і encryption.

### 1.6 Single-source-of-truth у міграціях

Один файл міграції, наприклад `cars/migrations/0007_car_color.py`,
накотиться **ідентично** на всі тенантські схеми через
`migrate_schemas --tenant`. Це усуває:

- Schema drift (одна схема відстала від іншої)
- Необхідність синхронізувати N окремих міграційних послідовностей
- Складність відкатів (один rollback, не N)

### 1.7 Прозорість для коду застосунку

Бізнес-код (views, serializers, models) **не знає про мульти-тенантність**.
Розробник пише:

```python
cars = Car.objects.all()
```

Те, що ця query виконається проти `alpha.cars_car` або `beta.cars_car`,
забезпечує middleware і custom DatabaseWrapper. Жодних `.using(...)`,
`.filter(tenant=...)`, ніяких декораторів — код виглядає як «звичайний Django».

Це дає:

- Низький поріг входу для нових розробників
- Швидку міграцію існуючих single-tenant-проектів
- Менший surface area для багів типу «забув додати tenant filter»

### 1.8 Маршрутизація через PG search_path

`search_path` — це **рідний механізм PostgreSQL**, що оптимізований за роки
розвитку:

- Резолвинг імені таблиці — B-tree look-up у `pg_namespace`
- Query planner розуміє search_path і генерує однакові плани незалежно від
  того, на якій схемі
- Statistics збираються per-table; tenant-таблиці отримують власні pg_statistic
- Indexes per-schema; bloat per-schema; vacuum per-schema

Це **не application-level** маршрутизація, що додавала б накладні витрати, а
вбудована функція PG, що працює завжди.

### 1.9 Готовий tooling та екосистема

| Інструмент                                    | Що дає                                                                                  |
|-----------------------------------------------|------------------------------------------------------------------------------------------|
| `pytest-django-tenants`                       | Pytest fixtures для тестування коду в контексті тенанта                                |
| `tenant_command`                              | `python manage.py tenant_command <cmd> --schema=alpha` — запуск будь-якої команди       |
| `TenantAdminMixin`                            | Інтеграція з Django admin                                                                |
| `migrate_schemas --executor=multiprocessing`  | Паралельне виконання міграцій по всіх тенантах                                          |
| `tenant-schemas-celery`                       | Інтеграція з Celery (див. §1.10)                                                         |

Пакет існує з 2015 року (форк від `django-tenant-schemas`), активно
підтримується, 1.7k+ GitHub stars, використовується у production десятків
SaaS-продуктів.

### 1.10 Celery + django-tenants — критично важлива інтеграція

Будь-який реальний Django SaaS використовує **Celery** для асинхронної
обробки: email-сендинг, генерація звітів, webhook-доставка, image
processing, scheduled cleanup, ML-inference, кеш-warming тощо. Без Celery
виходить або синхронно блокувати запити (UX-катастрофа), або заводити
окремий task-runner (зайва складність).

#### 1.10.1 Базова проблема: Celery worker не проходить через middleware

`TenantMainMiddleware` спрацьовує лише на HTTP-запитах. Celery-worker
отримує task із брокера (Redis/RabbitMQ) без жодного Host'а. Тому
**контекст тенанта потрібно передавати явно**.

**Підхід «schema як аргумент»**:

```python
@shared_task
def send_invoice_email(schema_name, order_id):
    from django_tenants.utils import schema_context
    with schema_context(schema_name):
        order = Order.objects.get(pk=order_id)
        send_email(order)
```

```python
# в view (в HTTP-контексті, schema вже встановлена middleware'ом)
from django.db import connection
send_invoice_email.delay(connection.schema_name, order.pk)
```

Працює, але потребує дисципліни — забути `schema_context` = task виконається
у public-схемі і дані поламає (або викине помилку якщо таблиць немає).

**Підхід «tenant-schemas-celery»**:

Окремий пакет
[`tenant-schemas-celery`](https://github.com/maciej-gol/tenant-schemas-celery)
інтегрує django-tenants із Celery на рівні фреймворка:

```python
# celery_app.py
from tenant_schemas_celery.app import CeleryApp

app = CeleryApp("myproject")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

```python
# tasks.py — нічого спеціального
@app.task
def send_invoice_email(order_id):
    order = Order.objects.get(pk=order_id)   # ← правильна схема вже виставлена
    send_email(order)
```

Як це працює всередині:

1. На стороні **producer'а** (HTTP-context): `tenant-schemas-celery` патчить
   task scheduling — при виклику `.delay()` бере поточний
   `connection.schema_name` і додає його в **task headers** (механізм
   Celery v4+).
2. На стороні **consumer'а** (Celery worker): pre-task signal зчитує header,
   виконує `schema_context(schema_name)` навколо тіла task'у, post-task —
   повертає public.
3. Якщо schema header відсутній (наприклад, task запущений з beat'у без
   явного контексту) — task виконується у public або у заданій за дефолтом
   схемі.

Це **прозоро для коду tasks** — як middleware прозорий для views.

#### 1.10.2 Чому schema-per-tenant добре масштабується з Celery

Окремий клас переваг, не очевидний без аналізу.

**Worker pool не зростає за тенантами.** Celery-воркер із prefork pool
тримає **один DB connection на процес**. Цей connection обслуговує task'и
будь-якого тенанта через `SET search_path`. Тобто **20 worker-процесів × 1
connection = 20 connections до PG**, незалежно від того, чи маємо 10 чи
1000 тенантів.

Альтернатива DB-per-tenant: воркер потенційно тримає по connection на
кожну тенант-БД, з якою працював → потенційно сотні connection'ів на воркер.

**Task queue може бути одна для всіх тенантів.** З schema-isolation'ом ти
можеш мати **єдину Celery queue** (наприклад `default`), куди потрапляють
task'и всіх тенантів. Будь-який воркер обробляє будь-який task. Це балансує
навантаження природно — гарячі тенанти не отримують dedicated infra.

Якщо колись потрібна пріоритизація (важливий клієнт → окрема queue), Celery
routing це підтримує:

```python
CELERY_TASK_ROUTES = {
    "tasks.heavy_report": {"queue": "premium_tenants"},
}
```

**Beat scheduling масштабується через fan-out.** Для періодичних задач
(cron-style) **не потрібно мати 1000 entries у `CELERY_BEAT_SCHEDULE`**.
Стандартний паттерн — один master beat task, що fan-out'ить на всіх
тенантів:

```python
CELERY_BEAT_SCHEDULE = {
    "daily-cleanup-fanout": {
        "task": "tasks.fanout_daily_cleanup",
        "schedule": crontab(hour=3, minute=0),
    },
}

@app.task
def fanout_daily_cleanup():
    """Один раз на день о 3:00 — для кожного тенанта запускає cleanup."""
    from tenants.models import Tenant
    for tenant in Tenant.objects.exclude(schema_name="public"):
        cleanup_old_data.apply_async(
            args=[],
            headers={"_schema_name": tenant.schema_name},
        )

@app.task
def cleanup_old_data():
    Order.objects.filter(created_at__lt=...).delete()   # вже у потрібній схемі
```

Один beat-process, одна schedule entry, масштабується на скільки завгодно
тенантів. Альтернатива з DB-per-tenant потребує per-DB beat configuration,
що додає складності.

**Persistent connections працюють у воркерах.** Celery prefork-worker
запускає task'и серіально в межах одного процесу. `CONN_MAX_AGE > 0` тут
безпечний (на відміну від PgBouncer transaction-mode). Connection живе
годинами, schema перемикається мікросекундами per task.

#### 1.10.3 Канонічна архітектура «django-tenants + Celery» у проді

```
                ┌──────────────────┐
                │  Redis/RabbitMQ  │  ← broker
                └────────┬─────────┘
                         │
            ┌────────────┼────────────┐
            ↓            ↓            ↓
       ┌─────────┐  ┌─────────┐  ┌─────────┐
       │ Worker  │  │ Worker  │  │ Worker  │  ← celery -A app worker
       │ pool=8  │  │ pool=8  │  │ pool=8  │
       └────┬────┘  └────┬────┘  └────┬────┘
            │            │            │
            └────────────┼────────────┘
                         ↓
                 ┌───────────────┐
                 │  PG cluster   │
                 │ public + N    │
                 │  schemas      │
                 └───────────────┘

       ┌─────────┐
       │  Beat   │  ← celery -A app beat
       │ (1×)    │     (тільки один процес — singleton)
       └────┬────┘
            │ періодично шле task'и в broker
            ↓
        (same broker)
```

| Компонент                    | Конфігурація                                                                |
|------------------------------|------------------------------------------------------------------------------|
| Broker                       | Redis (зазвичай) або RabbitMQ                                               |
| Result backend               | Redis (рекомендовано, щоб не зберігати results у public-схемі)             |
| `app` (Celery instance)      | `tenant_schemas_celery.app.CeleryApp` замість `celery.Celery`               |
| `CELERY_TASK_DEFAULT_QUEUE`  | `default` (одна queue для всіх тенантів)                                    |
| Worker pool                  | `prefork` (за дефолтом, безпечно зі schema-switching)                       |
| `CONN_MAX_AGE`               | 600 (10 хв persistent connections у воркерах)                              |
| `worker_prefetch_multiplier` | 1-4 (низько, щоб task'и не залипали на одному воркері)                     |
| Beat scheduler               | `django-celery-beat` (PeriodicTask у public schema)                         |

#### 1.10.4 Гачки і обмеження, про які треба знати

1. **Retry preserves headers**: Celery's `Task.retry()` зберігає task headers
   за дефолтом. Тобто `_schema_name` пройде у retry'ї коректно. Але при
   ручному перепосилі через `.apply_async()` треба явно прокинути header.
2. **Task chaining (canvas)**: `chord`, `group`, `chain` створюють
   child-tasks. `tenant-schemas-celery` пропагує schema header через
   канонічні Celery hooks, але треба тестувати кожен canvas-pattern після
   оновлення пакета.
3. **Eventlet/gevent pool**: НЕ використовувати з django-tenants без
   обережності. Eventlet робить many tasks concurrent в одному процесі, що
   ділять один connection. Schema switching стає race condition'ним.
   Альтернатива: prefork із багатьма процесами, або `--pool=solo` (один
   task за раз, без greenlet-пулу), або gevent з повним
   `monkey.patch_all()` + greenlet-local connections (з застереженнями
   §2.3 про modern Django).
4. **Beat storage**: `django-celery-beat` зберігає `PeriodicTask` у БД. Якщо
   `django_celery_beat` додано в `SHARED_APPS` — schedule shared (одна на
   платформу). Якщо в `TENANT_APPS` — per-tenant schedule (більше
   гнучкості, але треба beat-instance per tenant — не масштабується).
   Стандартний паттерн — SHARED + master fan-out task.
5. **Result backend choice**: DB-backed result backend (`django-celery-results`)
   при schema-per-tenant зберігає results у тенантні таблиці
   `django_celery_results_taskresult`. Бистрий вибір — Redis, щоб
   результати task'ів не наповнювали тенантські БД.
6. **Long-running tasks**: task, що йде годинами, може отримати connection
   drop **двох різних рівнів**, які лікуються різними засобами — не плутати:
   - **Broker-рівень** (Redis/RabbitMQ socket до Celery worker'а може
     дропнутись): `BROKER_CONNECTION_RETRY_ON_STARTUP=True` (retry конекта
     до брокера на старті) + `BROKER_CONNECTION_RETRY=True` (retry під час
     runtime) + `CELERY_TASK_ACKS_LATE=True` (worker ack'ить task **після**
     виконання, тож при crash'і task пере-доставиться іншому worker'у).
   - **DB-рівень** (Postgres-connection протух за `idle_session_timeout`
     поки task працював): `CONN_HEALTH_CHECKS=True` (Django робить
     `SELECT 1` перед reuse persistent connection) + TCP keepalive у
     `OPTIONS` + retry-on-stale декоратор з §3.5.4. Broker-настройки тут
     **не допомагають** — це інший socket до іншого сервера.
   Реалістичний long-running task потребує **обох** наборів.
7. **Monitoring**: Flower/Celery exporter не знають про tenant'и. Для
   observability — додати tenant tag у task headers і прокинути в
   logging/tracing (OpenTelemetry).

### 1.11 Загальне резюме сильних сторін

| Аспект                                  | Чому django-tenants виграшний для реальних SaaS-проектів                                                  |
|------------------------------------------|------------------------------------------------------------------------------------------------------------|
| **Connection economics**                 | Лінійні по воркерах web/Celery, не по тенантах. Скейлинг до тисяч тенантів без екзотичної інфраструктури. |
| **Operational unification**              | Один backup, один моніторинг, один failover, один TLS — менше operational surface area.                   |
| **Migration single-source-of-truth**     | Один міграційний файл накотиться на всі схеми. Параллельно через `--executor=multiprocessing`.            |
| **Code transparency**                    | Бізнес-код не знає про tenant'ів. Низький поріг входу, мало багів типу «забув tenant filter».              |
| **Native PostgreSQL mechanism**          | `search_path` — рідна функція PG, без application-level overhead.                                          |
| **Celery integration**                   | `tenant-schemas-celery` робить тенант-aware task'и прозорими, як middleware робить view'и.                |
| **Beat scaling**                         | Один beat-process + master fan-out task масштабується на 1000+ тенантів.                                  |
| **Mature ecosystem**                     | 9+ років розробки, pytest fixtures, admin integration, активна підтримка.                                  |
| **Cost**                                 | Open source, без vendor lock-in, стандартний PostgreSQL без extension'ів.                                  |

Кейси, де django-tenants **поступається** іншим архітектурам:

- Жорсткі вимоги фізичної ізоляції з конкретного BAA (див. §0)
- Сильно несиметричні тенанти (один тенант >50% навантаження)
- Потреба per-tenant Postgres tuning (`work_mem`, `statement_timeout`)
- Compliance-режим, що передбачає окремі encryption keys per tenant

У всіх інших сценаріях, особливо для проектів із Celery, schema-per-tenant
залишається оптимальним вибором.

---

## 2. Concurrency та django-tenants: уніфікований аналіз race conditions

`django-tenants` маршрутизує запити через **session-level state**
PostgreSQL connection'у — `SET search_path TO <schema>, public`. Будь-який
concurrent виконавчий контекст у тому самому процесі, що поділяє цей
connection, потенційно створює race condition із cross-tenant data
leak'ом. Цей розділ систематизує всі моделі виконання, у яких
django-tenants може застосовуватись (синхронний Celery, async Celery,
Django WSGI, Django ASGI, Channels), і дає аналіз безпеки кожної.

### 2.1 Фундамент: де живе schema state

#### Анатомія `connection.set_tenant()`

```python
# django_tenants/postgresql_backend/base.py (схематично)
from psycopg import sql

class DatabaseWrapper(...):
    def set_tenant(self, tenant):
        self.tenant = tenant
        self.set_schema(tenant.schema_name)

    def set_schema(self, schema_name):
        # ВАЖЛИВО: schema_name ЗАВЖДИ має бути pre-validated allowlist-регуляркою
        # на вищому рівні (`^[a-z_][a-z0-9_]{0,30}$` або еквівалент). Без цього
        # код нижче — identifier injection vector.
        self.schema_name = schema_name
        # При наступному виконанні запиту (безпечне квотування identifier'а
        # через psycopg.sql, не f-string):
        # cursor.execute(
        #     sql.SQL("SET search_path TO {schema}, public").format(
        #         schema=sql.Identifier(schema_name),
        #     )
        # )
```

Ключове спостереження: `search_path` — це **per-connection state у
PostgreSQL**. Однієї `SET`-команди достатньо, щоб усі наступні запити на
тому самому connection'і використовували новий `search_path`. Інші
connection'и не торкаються.

#### Де живе `connection`-обʼєкт у Python

`django.db.connection` — це proxy, що делегує на
`django.db.connections["default"]`. Обʼєкт `DatabaseWrapper` внутрішньо
використовує `threading.local()`-подібний механізм, щоб кожен **thread**
мав свій connection.

Це означає, що **видимість одного connection'у** для concurrent-контекстів
керується тим, як Python's runtime обходиться з thread-local storage:

| Concurrent unit                            | Що дає Python's runtime                                          |
|--------------------------------------------|-------------------------------------------------------------------|
| Process (fork)                             | Власний адресний простір → власний connection-pool              |
| Thread (CPython)                           | Власний thread-local → власний connection                         |
| Greenlet без monkey-patching               | Той самий thread → той самий connection (shared)                  |
| Greenlet із `gevent.monkey.patch_all()`    | `threading.local()` стає greenlet-local → власний connection      |
| Coroutine у asyncio event loop             | Один thread → той самий connection (shared)                       |
| Coroutine через `sync_to_async(thread_sensitive=True)` | dedicated thread-per-request → request-scope connection |

#### Уніфіковане формулювання проблеми

Race condition можливий тоді, і тільки тоді, коли:

1. У межах одного процесу одночасно виконуються кілька execution-контекстів (threads, greenlets, coroutines)
2. Ці контексти **шейрять** обʼєкт `connection`
3. **Хоча б один** із них перемикає `search_path` через `connection.set_tenant()` чи `schema_context()`

Якщо хоч одна з трьох умов не виконана — система безпечна.

### 2.2 Класифікація моделей виконання

Зведена таблиця безпеки:

| #  | Виконавча модель                                        | Multi-context per process? | Connection isolation                | Race? |
|----|---------------------------------------------------------|-----------------------------|--------------------------------------|--------|
| 1  | Celery `--pool=prefork`                                 | Ні                          | Per-process                          | ✅ Ні   |
| 2  | Celery `--pool=solo`                                    | Ні                          | Per-process                          | ✅ Ні   |
| 3  | Celery `--pool=threads`                                 | Так                         | Thread-local connection (Django def.)| ✅ Ні   |
| 4  | Celery `--pool=gevent` БЕЗ monkey-patch                 | Так                         | Shared                                | ❌ Race |
| 5  | Celery `--pool=gevent` ІЗ `monkey.patch_all()`          | Так                         | Greenlet-local (через monkey)         | ⚠️ Conditional |
| 6  | Celery `--pool=eventlet`                                | Так                         | Shared (як gevent без patch)         | ❌ Race |
| 7  | Celery async task + `asyncio.run()` (лінійний)          | Так у task, ні всередині    | Per-thread у task                    | ✅ Ні   |
| 8  | Celery async task + `asyncio.gather()` tenant-залежний  | Так                         | Shared у event loop                  | ❌ Race |
| 9  | Celery async task + `asyncio.create_task()` tenant-залежний | Так                     | Shared + lost context                | ❌ Race |
| 10 | `celery-aio-pool`                                       | Так                         | Shared у event loop                  | ❌ Race |
| 11 | Django WSGI (sync views + sync ORM)                     | Ні в одному thread'і        | Per-worker connection                | ✅ Ні   |
| 12 | Django ASGI sync middleware + async view + `aget`/`aall`| Так                         | Thread-sensitive (request-scope)     | ✅ Ні   |
| 13 | Django ASGI + `asyncio.gather()` той самий тенант       | Так                         | Shared (request thread)              | ✅ Ні   |
| 14 | Django ASGI + `asyncio.gather()` cross-tenant           | Так                         | Shared (request thread)              | ❌ Race |
| 15 | Django ASGI + `asyncio.create_task()` для background    | Так                         | Lost context                         | ❌ Race |
| 16 | Django ASGI streaming response із ORM-генератором       | Можливо                     | Залежить від implementation          | ⚠️ Edge cases |
| 17 | Django Channels (WebSocket consumers)                   | Так                         | Не через middleware                  | ⚠️ Manual setup |

Усі рядки з «Race» мають спільну ознаку — concurrent-units шейрять
обʼєкт connection. Усі рядки з «Ні» — execution-unit має свій connection
(через fork-process, thread-local, greenlet-local через monkey, чи
thread-sensitive sync_to_async). Це **не випадково** — наслідок того, що
django-tenants свідомо обрав «state on connection» як механізм маршрутизації.

### 2.3 Синхронні execution-моделі — деталі

#### prefork (рядок 1 у таблиці)

```bash
celery -A app worker --pool=prefork --concurrency=8
```

Master-процес форкає 8 child-процесів. Кожен виконує task'и
**послідовно**:

```
worker-1 timeline:
  T=0    bekommt task(schema=alpha)
  T=0    connection.set_tenant(alpha) → SET search_path TO alpha
  T=5ms  виконує ORM запити; усі → alpha.* tables
  T=20ms task завершений
  T=21   bekommt task(schema=beta)
  T=21   connection.set_tenant(beta) → SET search_path TO beta
```

Schema-switching відбувається **між task'ами**, не одночасно з ними.
Concurrent-execution унеможливлений семантикою prefork pool'у.

**Cost**: кожен child-процес — повний Python interpreter (~30-60MB RAM).
8 prefork × 4 host'и = 32 процеси × 50MB = 1.6GB RAM на cluster.

#### Threads (рядок 3)

```bash
celery -A app worker --pool=threads --concurrency=20
```

20 thread'ів в одному процесі. CPython GIL обмежує real CPU-parallelism,
але I/O може concurrent'ити. Django's `connections` має thread-local
storage за дефолтом → race condition'у нема.

**Caveats**:
- 20 thread'ів = 20 одночасних connection'ів до PG
- GIL обмежує CPU-bound parallelism
- Сторонні C-extension бібліотеки (lxml, cryptography) можуть мати власні thread-safety issues

#### gevent/eventlet без monkey-patch (рядки 4, 6) — НЕБЕЗПЕЧНО

```bash
celery -A app worker --pool=gevent --concurrency=500
```

500 greenlet'ів в одному thread'і. Cooperative scheduling. **Конкретна
анатомія race condition**:

```
T=0ms   greenlet G1 отримує task(schema=alpha, send_email)
T=0ms   G1: connection.set_tenant(alpha) → SET search_path TO alpha

T=2ms   G1: Order.objects.get(pk=42) — починає SQL-запит
T=2ms   G1: yield (чекає мережевої відповіді від PG)

T=2ms   Gevent scheduler підбирає greenlet G2
T=2ms   G2: connection.set_tenant(beta) → SET search_path TO beta
        ↑↑↑ ПОЛОМКА: connection — той самий обʼєкт, що в G1

T=5ms   G2: Order.objects.get(pk=99) виконується, search_path=beta
T=5ms   PG резолвить orders_order → beta.orders_order

T=8ms   G1 отримує відповідь PG (виконану проти beta!)
T=10ms  G1: order.save() → INSERT/UPDATE іде в beta.orders_order
        ↑↑↑ Дані alpha потрапили у beta. Cross-tenant data leak.
```

#### gevent із `monkey.patch_all()` (рядок 5)

```python
# entry-point файл Celery worker'а — ДО будь-якого Django import:
from gevent import monkey
monkey.patch_all()

import django
django.setup()
```

> ⚠️ **Перевір на твоїй версії Django перед тим, як на це покладатися.**
>
> Цей розділ ґрунтується на старій моделі Django (до ~3.0), де
> `ConnectionHandler` тримав connection-state у звичайному
> `threading.local()`. Тоді `monkey.patch_all()` патчив
> `threading.local` на greenlet-local — і `connections` справді
> ставав per-greenlet. Race condition зникав «безкоштовно».
>
> Сучасний Django (3.0+) використовує **`asgiref.local.Local`** замість
> `threading.local`. Його реалізація — власний dict, keyed по
> комбінації `(thread_id, asyncio_task_id)`, плюс fallback на
> `contextvars`. gevent **не патчить** asgiref.local.Local. Тобто на
> Django 3.0+ є реальна ймовірність, що `monkey.patch_all()` **НЕ дає**
> greenlet-local Django-connection'ів, і race condition залишається.
>
> Перш ніж викочувати gevent + monkey.patch_all() у прод — **запусти
> тест із §2.6** під реальним gevent-pool'ом і подивись, чи виявить
> він cross-tenant leak. Якщо тест червоний — patch_all не допомагає, і
> треба переходити на одну з безпечних альтернатив:
>
> 1. **`--pool=prefork` із більшою кількістю процесів** замість 500
>    greenlet'ів — основна ціль gevent'а (I/O-concurrency) досягається
>    повільніше, але без race conditions. Це найпростіший шлях.
> 2. **Custom DatabaseWrapper на ContextVar** (як у §2.5 / §3.3) — це
>    форк маршрутизації django-tenants, який працює і у gevent, і в
>    asyncio. Дорого, але архітектурно правильно.
> 3. **Окремий gevent-queue лише для tenant-agnostic task'ів** (нічого,
>    що ставить `set_tenant`/`schema_context`) — а tenant-aware'и
>    лишити у prefork-queue. Гібридний setup, складніший у моніторингу.

Якщо твоя перевірка показала, що patch_all дає очікувану ізоляцію
(можливо у певних версіях asgiref-у це працює) — далі діють старі
caveats:

1. **Connection multiplication**: 500 greenlets × власний connection = 500 одночасних PG connections з worker'а. На 4 worker'и = 2000. Потрібна більша Aurora instance class або PgBouncer.
2. **C-extension сумісність**: `psycopg2` може блокувати event loop. Альтернатива — `psycogreen` або `psycopg3`.
3. **Operational complexity**: memory leaks важче діагностувати, stack traces менш читабельні.

Setup #5 **робочий за умови, що patch_all справді ізолює connections**,
але вимагає 3-5x більше operational effort + явну верифікацію
ізоляції тестом.

### 2.4 Async execution-моделі — деталі

#### Базовий контекст: як Django async ORM працює внутрішньо

Django 4.1+ має async-методи (`aget`, `asave`, `aall`, `async for`).
Внутрішньо більшість із них — це **`sync_to_async` обгортки** з
`thread_sensitive=True`:

```python
# Псевдокод django/db/models/manager.py
class Manager:
    async def aget(self, *args, **kwargs):
        return await sync_to_async(self.get, thread_sensitive=True)(*args, **kwargs)
```

`thread_sensitive=True` означає: усі sync-частини в одному async-контексті
виконуються **на одному dedicated thread'і**. Для типового async-view із
прямолінійним ORM проблем нема.

#### Async-код всередині Celery task'у

**Лінійний (рядок 7) — безпечно**:

```python
@shared_task
def my_task():
    import asyncio
    asyncio.run(do_async_work())

async def do_async_work():
    car = await Car.objects.aget(pk=1)
    driver = await Driver.objects.aget(pk=2)
    return car.brand + driver.last_name
```

`prefork` → один процес. `asyncio.run()` створює event loop. `aget` →
`sync_to_async(thread_sensitive=True)` → один thread на весь call chain.
Безпечно.

**`asyncio.gather()` cross-tenant (рядок 8) — race**:

```python
async def do_async_work():
    async def fetch_alpha():
        with schema_context("alpha"):
            return await Car.objects.aall()

    async def fetch_beta():
        with schema_context("beta"):
            return await Car.objects.aall()

    a, b = await asyncio.gather(fetch_alpha(), fetch_beta())   # ← РАЗ
```

Обидві корутини concurrent у тому самому event loop, ставлять `search_path`
на shared connection. Race condition — той самий механізм, що у gevent без
monkey-patching.

**`asyncio.create_task()` (рядок 9) — lost context**:

```python
async def do_async_work():
    order = await Order.objects.aget(pk=1)
    asyncio.create_task(audit_log_async("alpha", "order_viewed", order.pk))
    return order
```

`create_task` запускає корутину у main event loop, поза thread-sensitive
context'ом. Audit task запуститься з невизначеним schema state.

#### Django ASGI async views

**Стандартний (рядок 12) — безпечно**:

```python
async def list_cars(request):
    cars = []
    async for car in Car.objects.all():
        cars.append(car.license_plate)
    return JsonResponse({"cars": cars})
```

Sync middleware ставить schema в request thread, async ORM-методи
лендять на той самий thread через `thread_sensitive=True`. Безпечно.

**`gather()` cross-tenant (рядок 14) — race**:

```python
async def cross_tenant_admin_view(request):
    async def for_alpha():
        with schema_context("alpha"):
            return await Order.objects.acount()

    async def for_beta():
        with schema_context("beta"):
            return await Order.objects.acount()

    a, b = await asyncio.gather(for_alpha(), for_beta())  # ← РАЗ
```

Race condition principle той самий, що у Celery сценарії #8.

**Streaming responses (рядок 16) — edge cases**:

```python
async def stream_orders(request):
    async def gen():
        async for order in Order.objects.all():
            yield json.dumps(order.as_dict()) + "\n"
    return StreamingHttpResponse(gen())
```

Async generator виконується **після** того, як основний view повернув
response. Цикл `async for` йде через `sync_to_async` — за thread_sensitive
має використати той самий request thread.

Каверз — глибший: оскільки `search_path` у django-tenants живе на
**connection-обʼєкті**, який лишається у per-thread pool'і між запитами,
послідовність може скластись так:

1. Request A прийшов на thread T, middleware виставив `search_path=alpha`
   на connection C.
2. View A повернув `StreamingHttpResponse(gen())`; генератор ще тільки
   починає yield'итись, але запит «формально» завершений — thread T
   повернувся у pool.
3. Request B приходить на тому ж thread'і T. Його middleware виконується
   синхронно, виставляє `search_path=beta` на тому самому connection C.
4. Генератор A прокидається на yield, робить наступний `async for`-крок —
   ORM ходить на connection C, де зараз `search_path=beta`. **Дані beta
   потрапляють у stream, який клієнт A читає як alpha.**

Тобто фікс — не «middleware має виконатися першим» (він і так виконується
першим у request lifecycle B), а **не тримати tenant-state на shared
connection**. Канонічне рішення — маршрутизація через ContextVar (§2.5,
§3.3), яка дає корутині A її власний copy contextvars поза межами
request lifecycle.

**Django Channels (рядок 17) — manual setup**:

Channels (WebSocket consumers) **не** проходять через звичайний middleware
chain. Tenant detection треба реалізувати окремо:

```python
from channels.middleware import BaseMiddleware
from django.db import connection
from tenants.models import Domain
from asgiref.sync import sync_to_async

class TenantChannelsMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        host = next((v.decode() for k, v in scope["headers"] if k == b"host"), "")
        host = host.split(":")[0]
        domain = await Domain.objects.select_related("tenant").aget(domain=host)
        await sync_to_async(connection.set_tenant, thread_sensitive=True)(domain.tenant)
        return await super().__call__(scope, receive, send)
```

Для GroupConsumer (broadcast) — кожен consumer instance має свій scope,
повідомлення з групи обробляються в різних threads, schema state не
пропагується автоматично.

### 2.5 Архітектурна альтернатива: ContextVar замість connection state

Усі race conditions мають один спільний корінь: **state живе на
connection-обʼєкті**. Архітектурно чистіша альтернатива — перенести state
на Python's runtime context, через `contextvars.ContextVar`:

```python
import contextvars
current_schema = contextvars.ContextVar("schema", default="public")
```

`ContextVar` має ключову властивість: при `asyncio.create_task(coro)` і
`asyncio.gather(c1, c2)` копія contextvars **успадковується** окремо для
кожної корутини. Race conditions у `gather()` зникають за визначенням.

| Властивість                                | Як це впливає на race conditions                            |
|---------------------------------------------|-------------------------------------------------------------|
| Per-thread isolation                        | Threads не шейрять value (як `threading.local`)            |
| Per-coroutine isolation                     | `create_task`, `gather` копіюють context — окремі value     |
| `set()` повертає `Token` → `reset()`        | Гарантоване відновлення попереднього стану                  |
| Не залежить від connection-обʼєкта          | Маршрутизація не потребує state на shared resource          |

**Проблема**: django-tenants за дизайном використовує connection-state.
Перехід на ContextVar — це **форк пакета** з заміною механізму
маршрутизації:

```python
from psycopg import sql

class TenantAwareDatabaseWrapper(DatabaseWrapper):
    def _cursor(self, name=None):
        cursor = super()._cursor(name)
        target_schema = current_schema.get()
        # ВАЖЛИВО: target_schema МАЄ бути pre-validated allowlist-регуляркою на
        # рівні, де він спочатку set'иться у ContextVar (middleware / Celery
        # integration). Без цього — identifier injection. Якщо схема приходить
        # із user-input — обов'язково regex-фільтр перед current_schema.set().
        if target_schema != cursor.connection.last_schema:
            cursor.execute(
                sql.SQL("SET search_path TO {schema}, public").format(
                    schema=sql.Identifier(target_schema),
                )
            )
            cursor.connection.last_schema = target_schema
        return cursor
```

**Cost**: значна доробка django-tenants — заміна `set_schema()` механізму
на ContextVar-aware варіант. Для більшості проектів — стандартного
django-tenants із prefork-Celery і обережним використанням async-у
достатньо.

### 2.6 Діагностика і тестування

#### Як перевірити, який pool використовує ваш Celery

```bash
celery -A app inspect stats
# у виводі шукай:
#   "pool": {
#     "implementation": "celery.concurrency.prefork:TaskPool",
#     ...
#   }
```

#### Synthetic reproduction для thread pool

```python
# tests/test_isolation_threads.py
from concurrent.futures import ThreadPoolExecutor
from django_tenants.utils import schema_context
from cars.models import Car


def _query_tenant(schema):
    with schema_context(schema):
        import time
        time.sleep(0.01)  # симулюємо I/O
        return sorted(Car.objects.values_list("license_plate", flat=True))


def test_threads_isolated(setup_two_tenants):
    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(_query_tenant, ["alpha", "beta"] * 50))

    for i, plates in enumerate(results):
        expected_tenant = "alpha" if i % 2 == 0 else "beta"
        assert plates_belong_to_tenant(plates, expected_tenant)
```

#### Reproduction для gather() cross-tenant

```python
@pytest.mark.asyncio
async def test_gather_cross_tenant_isolated(setup_two_tenants):
    async def fetch_for(schema):
        with schema_context(schema):
            await asyncio.sleep(0.01)
            # `QuerySet.aiterator()` ПОВЕРТАЄ async iterator, а не coroutine —
            # його НЕ await'ять, через нього ходять `async for`. Робити
            # `list(await qs.aiterator())` = TypeError (object async_generator
            # can't be used in 'await' expression).
            plates = []
            async for plate in Car.objects.values_list("license_plate", flat=True):
                plates.append(plate)
            return sorted(plates)

    results = await asyncio.gather(
        fetch_for("alpha"),
        fetch_for("beta"),
        fetch_for("alpha"),
        fetch_for("beta"),
    )
    assert results[0] == results[2]
    assert results[1] == results[3]
    assert results[0] != results[1]
```

#### Production assertion

```python
def _assert_schema(expected_schema: str) -> None:
    actual = connection.schema_name
    if actual != expected_schema:
        raise RuntimeError(
            f"Schema integrity violation: expected={expected_schema}, "
            f"actual={actual}. Possible race condition."
        )

@app.task(bind=True)
def my_task(self, ...):
    expected = (self.request.headers or {}).get("_schema_name", "public")
    _assert_schema(expected)
```

#### Load testing із cross-tenant integrity check

```python
async def hit_random_tenant(client, tenants, tokens):
    tenant = random.choice(tenants)
    resp = await client.get(
        f"https://{tenant}.example.com:8000/api/cars/",
        headers={"Authorization": f"Bearer {tokens[tenant]}"},
    )
    plates = {c["license_plate"] for c in resp.json()}
    expected = expected_plates_for(tenant)
    leaked = plates - expected
    if leaked:
        raise AssertionError(f"Tenant {tenant} got leaked plates: {leaked}")
```

Race conditions виявляються лише під contention'ом, не у unit-тестах.

### 2.7 Рекомендації за сценаріями

#### Decision matrix

| Сценарій / навантаження                                | Рекомендація                                                                |
|---------------------------------------------------------|------------------------------------------------------------------------------|
| Стандартний REST API без async, з Celery email/notifications | WSGI gunicorn + Celery `--pool=prefork` — **default**                   |
| CPU-bound Celery task'и                                 | Celery `--pool=prefork --concurrency=cores`                                  |
| Багато I/O-bound task'ів (webhooks, external APIs)      | Hybrid: prefork queue для tenant-aware + gevent queue для tenant-agnostic   |
| Real-time UI потреба (WebSockets/SSE)                   | ASGI з Channels + manual tenant middleware; Celery лишити prefork           |
| Heavy admin dashboards із cross-tenant даними           | Серіальні await замість gather; або форк django-tenants на ContextVar       |
| Hyperscale (>100K req/sec, потребує greenlet'и)         | gevent + `monkey.patch_all()` + `psycopg3` + PgBouncer; ретельне тестування |
| Compliance-режим із суворою ізоляцією                   | DB-per-tenant архітектура (framing §0, implementation §3); не лише різні воркер-pools |

#### Anti-patterns, яких варто уникати

1. **`--pool=gevent` без monkey-patching** для tenant-aware task'ів — гарантований race condition.
2. **`asyncio.gather()` із cross-tenant `schema_context()`** — race condition незалежно від pool'у.
3. **`asyncio.create_task()` для tenant-залежної роботи** — lost schema context. Замінити на Celery task із tenant header.
4. **Streaming responses із ORM-генераторами**, що мають довге життя — request thread holding schema state може зачепити наступні запити.
5. **Django Channels без власного tenant middleware** — consumer не має schema context.
6. **`celery-aio-pool` для tenant-залежних task'ів** — той самий клас проблем, що gevent без monkey.

#### Pre-flight checklist при додаванні async-коду до tenant-aware проекту

- [ ] Pool Celery — `prefork` (або solo для debug)?
- [ ] Усі async-views проходять через sync `TenantMainMiddleware`?
- [ ] `asyncio.gather()` використовується лише для запитів у **той самий тенант**?
- [ ] `asyncio.create_task()` НЕ використовується для tenant-залежної роботи?
- [ ] Streaming responses із ORM-генераторами — тестовані під load?
- [ ] Якщо є Channels — є власний tenant middleware у `ASGI_APPLICATION`?
- [ ] Тест із §2.6 пройдено перед merge'ом?
- [ ] Production assertion із §2.6 додано в critical paths?

### 2.8 Резюме

| Принцип                                                     | Наслідок                                                |
|--------------------------------------------------------------|----------------------------------------------------------|
| Race condition виникає, коли concurrent units шейрять connection | Уникати того, щоб концурент-юніти шейрили connection-обʼєкт |
| Process-per-task або thread-per-task = ізольований connection | prefork і threads pool безпечні                          |
| Greenlet-per-task потребує monkey-patching для ізоляції       | gevent без monkey — небезпечно                            |
| Async coroutines у одному event loop шейрять connection      | `asyncio.gather()` cross-tenant — небезпечно             |
| `sync_to_async(thread_sensitive=True)` дає thread-scope isolation | Стандартні async-views Django + ORM — безпечні        |
| ContextVar — async-native альтернатива connection-state       | Архітектурне рішення для serious async-stack             |

**Базове правило**: триматися prefork для Celery; ASGI лише там, де він
критично потрібен; уникати `gather()`/`create_task()` із tenant-switching;
робити load-тести на cross-tenant integrity при будь-якому переході на
high-concurrency execution model.

---

## 3. DB-per-tenant на django-tenants із Django 5.2, Celery, Aurora і планом переходу на async

Розкладу архітектуру шар за шаром, із кодовими прикладами, що кожен
можна виконати без розуміння попередніх. Підхід: **взяти django-tenants
як скелет** (`Tenant`/`Domain`-моделі, `TenantMainMiddleware`-патерн,
management команди), але **переписати механізм маршрутизації** із
PostgreSQL `search_path` на Django DATABASE-aliasing. Це не «використання
django-tenants як є» — це його **форк**.

### 3.1 Стек і версії пакетів

#### 3.1.1 PostgreSQL driver: `psycopg[c]` (psycopg 3) — обов'язково

```
psycopg[c]==3.2.3
# або для dev / контейнерів без compile-tools:
# psycopg[binary]==3.2.3
```

**Чому psycopg3, а не psycopg2**:

1. **Native async support**. Phase 2 переходить на ASGI з async-ORM. psycopg2 не має async API; будь-яка асинхронність буде через `sync_to_async`-обгортки в thread pool — це деградує latency у hot-path'ах. psycopg3 має `AsyncConnection` і `AsyncCursor` із прямим asyncio-interface'ом.
2. **Підтримка Django 5.x**. Django 4.2 додав експериментальну підтримку psycopg3; Django 5.0+ робить його повноправним. Django 5.2 (наш стек) приймає `psycopg` 3.1+ як перший-клас backend.
3. **Server-side parameters**: psycopg3 використовує server-side binary protocol для параметризованих запитів — швидше і безпечніше за psycopg2.
4. **Prepared statements API**: psycopg3 має explicit `Connection.prepare()` контроль. Це критично для PgBouncer transaction-mode (де неконтрольовані prepared statements викликають connection pinning).
5. **psycopg3 native pooling**: вбудований `psycopg_pool.ConnectionPool` і `AsyncConnectionPool`.

**`-binary` vs `[c]`**:

- `psycopg[binary]` — wheel із linked libpq. Зручно для dev/CI, **ризик у production**: bundled libpq може бути старим (без security патчів).
- `psycopg[c]` — compile з системної libpq. Системні оновлення libpq автоматично підтягуються.
- Production = `psycopg[c]`. Dev = `psycopg[binary]`.

#### 3.1.2 Django 5.2 — фіксуємо мінорну версію

```
Django==5.2.13
```

Django 5.2 має стабільну async ORM (`aget`, `aall`, `acreate`, `async for`, `aiterator`), покращений `CONN_HEALTH_CHECKS`, ASGI handler із кращою thread-pool інтеграцією через `asgiref`.

#### 3.1.3 Celery — версія і пакети

```
celery==5.4.0
redis==5.0.8         # broker + result backend + pub/sub invalidation
flower==2.0.1        # моніторинг (опційно)
```

**НЕ використовуємо `tenant-schemas-celery`**. Цей пакет розрахований на schema-перемикання через `schema_context()`. У DB-per-tenant ми перемикаємо DB alias, не schema. Потрібна власна Celery-інтеграція (приклад у §3.3.7).

**Чому Redis для broker і result backend**: не залежить від тенантських БД, швидкий, один інстанс elasticache обслуговує всі тенанти, заодно використовується для pub/sub cache invalidation.

#### 3.1.4 Connection pooler: RDS Proxy або PgBouncer

**RDS Proxy (managed)**: тариф ~$0.015 за vCPU-hour (per vCPU underlying RDS-інстансу), підтримує IAM auth pass-through, Multi-AZ failover transparency, transaction-mode pooling. Обмеження по client connections: `MaxConnectionsPercent × max_connections інстансу, до якого Proxy підключений` (за дефолтом `MaxConnectionsPercent = 100%`, тобто client-limit = `max_connections` instance'у).

**PgBouncer (self-hosted)**: безкоштовно, більше контролю, wildcard `[databases] *` синтаксис для 1000 DBs.

**Вибір**: RDS Proxy для production (менше operational burden), PgBouncer для on-prem.

#### 3.1.5 ASGI server (для phase 2)

```
uvicorn[standard]==0.32.0    # для phase 2
```

У phase 1 (sync) — `gunicorn` + sync workers; у phase 2 — `gunicorn -k uvicorn.workers.UvicornWorker`.

#### 3.1.6 AWS і допоміжні пакети

```
boto3==1.35.40                   # AWS SDK — Secrets Manager, IAM auth tokens
django-redis==5.4.0              # cache backend на Redis для inter-worker invalidation
```

#### 3.1.7 Що **не** ставимо

- ❌ `psycopg2`/`psycopg2-binary` — застаріле, без async, заважатиме phase 2
- ❌ `tenant-schemas-celery` — для schema-варіанту, не для DB-per-tenant
- ❌ `gevent`/`eventlet` — race conditions у tenant-aware коді
- ❌ `django-celery-beat` із per-tenant schedules — занадто складно для 1000 тенантів; використовуємо master fan-out task

### 3.2 Архітектурні складнощі — connection math

#### 3.2.1 Загальна модель навантаження

Припустимо realistic SaaS:

- **1000 тенантів**, нерівномірний скос: top-10 тенантів дають 60% трафіку
- **Phase 1**: gunicorn із 4 синхронними воркерами × 4 host'и = 16 worker-процесів. **16 concurrent web requests**.
- **Phase 2**: uvicorn на тих самих 4 host'ах, 1 process per CPU = ~16 процесів. Кожен async — обслуговує 100+ concurrent requests одночасно. **1600+ concurrent web requests**.
- **Celery**: 4 host'и × 8 prefork workers = 32 worker-процесів. **32 concurrent tasks**.

#### 3.2.2 Connection math БЕЗ пулера, phase 1 sync

- За день worker торкнеться ~80% активних тенантів (800 tenants)
- 16 web workers × 800 tenant-connections = **12,800 connections** до Aurora
- + 32 Celery workers × 800 = 25,600
- **Total ≈ 38,400 connections**

Aurora db.r5.4xlarge → `max_connections ≈ 13,600`. **Без пулера колапс**.

#### 3.2.3 Connection math БЕЗ пулера, phase 2 async

- 16 async processes × 100 concurrent requests/process × 1 connection per request = **1600 active connections**
- Якщо connection cache'ється — стільки ж, скільки в sync (12,800+)

Phase 2 не покращує connection math сама по собі.

#### 3.2.4 Connection math ІЗ пулером (transaction-mode)

- Django process відкриває connection до пулера (cheap, ~1ms)
- Пулер тримає невеликий per-DB backend pool до Aurora
- Per-DB `pool_size=5` × 1000 DBs = **5000 backend connections** до Aurora
- Aurora r5.4xlarge `max_connections ≈ 13,600` → запас

#### 3.2.5 Caveats transaction-mode у нашому контексті

API-only DRF знімає ~80% обмежень transaction-mode:

| Caveat                          | Дія                                                                                  |
|---------------------------------|--------------------------------------------------------------------------------------|
| Persistent connections          | `CONN_MAX_AGE=0` (стратегія B, див. §3.4.2) АБО `CONN_MAX_AGE>0` + LRU eviction + `CONN_HEALTH_CHECKS=True` (стратегія D, рекомендована, див. §3.4.2 + §3.5.2) |
| Advisory locks                  | Якщо потрібні — `pg_try_advisory_xact_lock()` (transaction-scoped)                   |
| LISTEN/NOTIFY                   | Не потрібен (Redis pub/sub)                                                          |
| `SET TIMEZONE`                  | `USE_TZ=True` + `TIME_ZONE="UTC"` + не передавати timezone в `OPTIONS`                |
| Prepared statements             | `prepare_threshold=None` в `OPTIONS`                                                 |
| Server-side cursors             | Уникати `.iterator()` в API; export-jobs через окремий direct alias                  |
| Pool exhaustion під spike       | `reserve_pool_size=2-3` + `max_db_connections=30` per database                       |

#### 3.2.6 Celery worker connection lifecycle

Celery prefork → один процес обслуговує task'и послідовно. Per-worker connection cache живе до `CONN_MAX_AGE` секунд (за §3.3.4 — 10 хв) або до явного eviction'у з §3.4. Проблеми: backend у пулері простояв довше, ніж pgbouncer `server_idle_timeout` чи Aurora `idle_session_timeout`; TCP-зʼєднання Django→пулер могло бути drop'ene NAT'ом; наступний запит — `OperationalError`. Детально у §3.5.

### 3.3 Зміни в django-tenants для DB-per-tenant

#### 3.3.1 `Tenant`-модель: розширення для зберігання DB-конфігу

**Чому**: django-tenants за дизайном тримає `schema_name`-поле; для DB-per-tenant потрібно зберігати endpoint, db_name, секрет/ARN.

```python
# tenants/models.py
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    """
    DB-per-tenant variant. `schema_name` лишається як унікальний human-readable
    ID тенанта (alpha, beta, ...), але вже НЕ відповідає Postgres-схемі.
    Натомість він є частиною формули імені БД: db_name = f"tenant_{schema_name}".
    """
    name = models.CharField(max_length=120, unique=True)
    created_on = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    auto_create_schema = False
    auto_drop_schema = False


class Domain(DomainMixin):
    """Hostname → Tenant. Без змін від django-tenants."""
    pass


class DBConfig(models.Model):
    """Конфіг підключення до physical Aurora DB кожного тенанта.

    NB: `on_delete=CASCADE` каскадно видаляє лише master-row (DBConfig +
    Domain + сам Tenant). `DROP DATABASE tenant_<schema>` на Aurora
    автоматично НЕ виконується — фізична БД з усіма даними тенанта
    лишається висіти orphaned, з'їдає storage, видно у `\\l`.
    Якщо потрібен реальний clean-up — це окрема компанійон-команда (не
    реалізована у прикладі), яка робить `DROP DATABASE` ПІСЛЯ
    `Tenant.delete()` під керівництвом адміна. Або навмисний дизайн —
    soft retention для compliance.
    """
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="db_config",
    )
    db_name = models.CharField(max_length=63)
    db_host = models.CharField(max_length=255)
    db_port = models.PositiveSmallIntegerField(default=5432)
    db_user = models.CharField(max_length=63)
    # blank=True лишаємо як майбутній hook для IAM-auth path (§3.3.5):
    # коли DBConfig.secret_arn == "", _resolve_password() має fallback'итись
    # на get_iam_token(db_host, db_port, db_user, region). У поточному коді
    # registry такий fallback ще НЕ підключений — поки secret_arn ОБОВ'ЯЗКОВИЙ
    # на рівні бізнес-логіки, попри blank=True у моделі. Якщо IAM-варіант
    # ввімкнено — інтегруй get_iam_token у _resolve_password і ця нестиковка
    # зникає сама собою.
    secret_arn = models.CharField(max_length=255, blank=True)
    cluster_id = models.CharField(max_length=64, default="primary")
    region = models.CharField(max_length=16, default="us-east-2")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "tenants"
        indexes = [models.Index(fields=["cluster_id"])]
```

#### 3.3.2 ContextVar-based маршрутизація — фундамент

**Чому**: thread-local-based маршрутизація працює в sync, але **ламається** в async (`asyncio.gather()` — race condition). ContextVar — async-native. Якщо одразу не закласти його — phase 2 буде повним переписуванням маршрутизації.

> **Врізка: як працює `contextvars.ContextVar` і чому критично оголошувати в одному місці**
>
> `ContextVar` (PEP 567) — стандартний Python-примітив, що поводиться подібно до thread-local'у, але:
> - При `asyncio.create_task(coro)` і `asyncio.gather(c1, c2)` копія значення успадковується **окремо** для кожної корутини — set в одній не зачіпає іншу.
> - Між threads — окремі значення (як `threading.local`).
> - У межах sync-callstack у тому самому threadʼі — спільне значення.
>
> **Ідентифікація ContextVar — за обʼєктом, а не за іменем**. Рядок `"current_tenant"`, що передається в конструктор, — лише debug-label для traceback'ів і репрезентації. Два різні `contextvars.ContextVar("current_tenant")`, оголошені в різних модулях, — це **два незалежні обʼєкти**, які нічого не знають один про одного. Якщо middleware виставить значення в свій ContextVar, а router зачитає зі свого — router отримає `None` і маршрутизація мовчки не працюватиме.
>
> Тому в проекті ContextVar-змінні оголошуються в **єдиному місці**, а всі інші модулі імпортують готові обʼєкти.

Єдиний модуль із оголошенням — `tenants/routing/context.py`:

```python
# tenants/routing/context.py
"""
ЄДИНИЙ модуль із оголошенням усіх tenant-related ContextVar.

Усі інші модулі (middleware, router, celery integration, утиліти) ПОВИННІ
імпортувати готовий обʼєкт `current_tenant` звідси, а НЕ створювати власний:

    from tenants.routing.context import current_tenant
    token = current_tenant.set("alpha")
    ...
    current_tenant.reset(token)

Заборонено: `contextvars.ContextVar("current_tenant", ...)` будь-де інде —
це дасть НОВИЙ обʼєкт, ізольований від того, який читає router.
"""
import contextvars
from typing import Optional

# Поточний тенант для активного execution context (request / Celery task / тощо).
# None = маршрутизація йде на master DB ("default" alias).
current_tenant: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_tenant",
    default=None,
)


def get_current_db_alias() -> str:
    """Convenience: Django DB alias для поточного тенанта; 'default' якщо тенант не виставлений."""
    schema = current_tenant.get()
    return f"tenant_{schema}" if schema else "default"
```

Якщо в майбутньому знадобиться ще одна tenant-related ContextVar (наприклад,
`current_user_role` чи `current_request_id`) — додавати її **в той самий
файл**, не плодити окремі модулі.

#### 3.3.3 DATABASE_ROUTERS: куди ORM пише

```python
# tenants/routing/db_router.py
from tenants.routing.context import current_tenant


class TenantDBRouter:
    SHARED_APP_LABELS = {
        "tenants", "contenttypes", "auth", "sessions", "admin",
    }

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.SHARED_APP_LABELS:
            return "default"
        schema = current_tenant.get()
        return f"tenant_{schema}" if schema else "default"

    def db_for_write(self, model, **hints):
        return self.db_for_read(model, **hints)

    def allow_relation(self, obj1, obj2, **hints):
        return obj1._state.db == obj2._state.db

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == "default":
            return app_label in self.SHARED_APP_LABELS
        return app_label not in self.SHARED_APP_LABELS
```

#### 3.3.4 Connection registry — динамічна реєстрація tenant DB конфігів

**Чому**: `settings.DATABASES` за дефолтом — static dict. Тримати в ньому 1000 entries неможливо. Динамічна реєстрація + per-worker cache.

> ⚠️ **Увага: код далі мутує `connections._connections` — приватний атрибут Django**
>
> Атрибут починається з підкреслення (`_connections`) — Django не гарантує його стабільності між мінорними версіями. Зараз (Django 5.2) він існує і має очікувану семантику; у 5.3/6.0 може бути перейменований чи прихований. Це **запинає проект на конкретну мінорну версію Django** і обов'язково перевірятиметься при кожному апгрейді.
>
> Загальне правило: **використання приватного / недокументованого API — це технічний борг**. Воно працює, але:
> - Не покривається SemVer-обіцянками апстріму
> - Не з'являється у release notes — breaking change може пройти непомітно
> - CI/тести вашого проекту виявлять поломку, але після апгрейду
> - Static type checkers (mypy, pyright) скаржитимуться на `Unresolved attribute reference`
>
> Якщо хочеш цього уникнути — **див. §3.7**, де наведена альтернатива з використанням **тільки публічного Django-API** (`connections[alias].close()` + in-place мутація `connections.databases[alias]`). Trade-off: невеликий memory-overhead (~5KB per cached wrapper per thread), що несуттєво для більшості сценаріїв.

```python
# tenants/routing/registry.py
"""
Динамічний registry tenant DB-конфігів.

Pattern: optimistic «compute outside, mutate inside».
  - Slow I/O (DBConfig lookup, Secrets Manager call) виконується БЕЗ
    глобального lock'а. Кілька паралельних потоків можуть продублювати
    цю роботу — це OK: ~100ms × N марно витраченого часу проти
    блокування N потоків на тих самих 100ms.
  - Глобальний `_lock` береться ТІЛЬКИ на фінальну мутацію
    `connections.databases` (~µs).

Чому це важливо:
  - Під sync gunicorn (1 thread/process) lock-contention'у нема — Option 1
    нічого не покращує, але й не шкодить.
  - Під ASGI/uvicorn (десятки concurrent requests на event loop, кожен
    породжує свій thread через sync_to_async(thread_sensitive=True))
    глобальний lock на I/O створював би лінійну деградацію cold-start'у
    від concurrency. Option 1 — передумова до Phase 2.
"""
import threading
import time

from django.db import connections


_lock = threading.RLock()
_meta: dict[str, dict] = {}
_TTL_SECONDS = 300

# Кеш boto3 Secrets Manager клієнтів per region. Створення клієнта
# (~30-50ms, бо boto3 парсить service-model JSON) повторно не платимо.
# Самі виклики get_secret_value на одному клієнтові thread-safe.
_secrets_clients: dict[str, object] = {}
_secrets_clients_lock = threading.Lock()


def _get_secrets_client(region: str):
    client = _secrets_clients.get(region)
    if client is None:
        with _secrets_clients_lock:
            client = _secrets_clients.get(region)
            if client is None:
                import boto3
                client = boto3.client("secretsmanager", region_name=region)
                _secrets_clients[region] = client
    return client


def ensure_tenant_db_registered(schema_name: str) -> str:
    alias = f"tenant_{schema_name}"
    now = time.time()

    # ───── Fast path — без локу ─────
    cached = _meta.get(schema_name)
    if cached and (now - cached["ts"]) < _TTL_SECONDS and alias in connections.databases:
        return alias

    # ───── Slow I/O — ЗОВНІ локу ─────
    cfg = _fetch_dbconfig(schema_name)

    # Pre-check ще до Secrets Manager — якщо version у кеші актуальна, виходимо.
    cached = _meta.get(schema_name)
    if (
        cached
        and alias in connections.databases
        and cached.get("version") == cfg.updated_at
    ):
        cached["ts"] = time.time()
        return alias

    password = _resolve_password(cfg)
    new_config = _build_config(cfg, password)

    # ───── Mutation only — під локом, ~µs ─────
    with _lock:
        # Final re-check: між нашим I/O і acquire'ом lock'а інший thread
        # міг встигнути зареєструвати конфіг з тією ж або новішою версією.
        cached = _meta.get(schema_name)
        if (
            cached
            and alias in connections.databases
            and cached.get("version") >= cfg.updated_at
        ):
            cached["ts"] = time.time()
            return alias

        if alias in connections.databases:
            try:
                connections[alias].close()
            except Exception:
                pass
            connections._connections.pop(alias, None)
        connections.databases[alias] = new_config
        _meta[schema_name] = {"ts": time.time(), "version": cfg.updated_at}

    return alias


def _fetch_dbconfig(schema_name: str):
    from tenants.models import DBConfig
    return (
        DBConfig.objects.using("default")
        .select_related("tenant")
        .get(tenant__schema_name=schema_name)
    )


def _build_config(cfg, password: str) -> dict:
    # Узгоджена пара з рекомендованою стратегією D (LRU touch, §3.4):
    #   CONN_MAX_AGE=600 — connection persistent до 10хв, потім Django
    #                       сам закриває. LRU eviction може закрити раніше.
    #   CONN_HEALTH_CHECKS=True — перед reuse persistent connection Django
    #                       робить SELECT 1; ловить stale від NAT/pgbouncer.
    # Якщо переходиш на стратегію B (CloseTenantConnectionMiddleware) —
    # виставляй "CONN_MAX_AGE": 0 і прибирай "CONN_HEALTH_CHECKS"
    # (воно no-op без persistent connections).
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": cfg.db_name,
        "USER": cfg.db_user,
        "PASSWORD": password,
        "HOST": cfg.db_host,
        "PORT": str(cfg.db_port),
        "CONN_MAX_AGE": 600,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "sslmode": "require",
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000",
            "prepare_threshold": None,
        },
        "AUTOCOMMIT": True,
        "TIME_ZONE": None,
        "USE_TZ": True,
        "ATOMIC_REQUESTS": False,
        "TEST": {},
    }


def _resolve_password(cfg) -> str:
    if not cfg.secret_arn:
        raise RuntimeError(
            f"DBConfig for {cfg.tenant.schema_name} has no secret_arn"
        )
    client = _get_secrets_client(cfg.region)
    return client.get_secret_value(SecretId=cfg.secret_arn)["SecretString"]


def invalidate_tenant(schema_name: str) -> None:
    with _lock:
        _meta.pop(schema_name, None)
        alias = f"tenant_{schema_name}"
        if alias in connections.databases:
            try:
                connections[alias].close()
            except Exception:
                pass
            connections._connections.pop(alias, None)
```

#### 3.3.5 Альтернативний password resolver: IAM-auth tokens (Aurora-specific)

**Чому**: статичні паролі — це rotation pain, ризик leak. Aurora підтримує IAM-auth: client генерує токен через `boto3` локально, токен дійсний 15 хвилин, не зберігається в БД.

```python
# tenants/routing/iam_auth.py
"""
IAM-auth resolver для Aurora.

Той самий «compute outside, mutate inside» pattern, що й у §3.3.4:
  - `generate_db_auth_token` сам по собі — client-side операція (SigV4-підписаний
    URL, без network call), ~1-2ms. Але створення `boto3.client("rds")` —
    ~30-50ms (парсинг service-model JSON), і це повторювати марно.
  - Тому кешуємо RDS-клієнт per region (singleton); сам токен генеруємо
    ЗОВНІ локу; lock тримаємо тільки на вставлення у `_token_cache` (~µs).

Виграш у sync gunicorn'і помірний; під ASGI/Phase 2 — критичний, з тих самих
причин, що описано у docstring §3.3.4 registry.
"""
import threading
import time

import boto3

_token_cache: dict[tuple, tuple[str, float]] = {}
_token_lock = threading.Lock()
_TOKEN_REFRESH_BEFORE_EXPIRY = 180

# Кеш boto3 RDS-клієнтів per region.
_rds_clients: dict[str, object] = {}
_rds_clients_lock = threading.Lock()


def _get_rds_client(region: str):
    client = _rds_clients.get(region)
    if client is None:
        with _rds_clients_lock:
            client = _rds_clients.get(region)
            if client is None:
                client = boto3.client("rds", region_name=region)
                _rds_clients[region] = client
    return client


def get_iam_token(db_host: str, db_port: int, db_user: str, region: str = "us-east-2") -> str:
    key = (db_host, db_port, db_user)
    now = time.time()

    # Fast path — без локу.
    cached = _token_cache.get(key)
    if cached and cached[1] - now > _TOKEN_REFRESH_BEFORE_EXPIRY:
        return cached[0]

    # Token-generation ЗОВНІ локу. generate_db_auth_token — client-side
    # SigV4 sign, без network round-trip. Паралельні виклики можуть
    # дублювати (1-2ms кожен), але lock-contention'у не створюють.
    client = _get_rds_client(region)
    token = client.generate_db_auth_token(
        DBHostname=db_host,
        Port=db_port,
        DBUsername=db_user,
    )
    expiry = now + 900

    # Mutation only.
    with _token_lock:
        cached = _token_cache.get(key)
        if cached and cached[1] - now > _TOKEN_REFRESH_BEFORE_EXPIRY:
            return cached[0]
        _token_cache[key] = (token, expiry)

    return token
```

#### 3.3.6 Middleware: установка ContextVar при HTTP-запиті

> ⚠️ **Цей middleware — навчальний приклад, а не drop-in production-код.**
>
> Нижче `Domain` резолвиться через `Domain.objects.using("default").filter(domain=host).first()` **на кожен HTTP-запит**. Це означає:
>
> - **1 000 RPS = 1 000 SELECT'ів за секунду до master DB**, тільки заради того, щоб довідатись, на яку tenant-БД маршрутизувати. Master стане першим bottleneck'ом — раніше, ніж самі tenant DB.
> - **Master DB опосередковано стає SPOF для usability**: якщо master тимчасово недоступний, **жоден** tenant-запит не пройде, навіть якщо tenant-DB живі. Архітектурно ми вибудовуємо ізоляцію — але цей middleware зводить її нанівець на read-path'і.
> - Latency: +1-5 ms на кожен запит, плюс шум у `pg_stat_statements`.
>
> **У реальній системі цей lookup ОБОВ'ЯЗКОВО треба кешувати.** Варіанти:
>
> 1. **In-process `lru_cache` із TTL** (наприклад, `cachetools.TTLCache(maxsize=10_000, ttl=300)`) — найдешевше, але кеш per worker, інвалідація — через ту саму Redis pub/sub-шину з §3.3.12 (додати окремий channel `domain_cache_invalidate`).
> 2. **`django-redis` як cross-worker cache**: `cache.get_or_set(f"domain:{host}", lambda: ..., timeout=300)` — один Redis round-trip замість DB-запиту, інвалідація через TTL або явний `cache.delete`.
> 3. **Hot path без I/O**: pre-load всіх `Domain → Tenant` mappings при старті процесу + Redis pub/sub для оновлень. Найшвидше (~µs), складніше підтримувати.
>
> Нижчий приклад залишає прямий DB-lookup лише для **читабельності розділу про ContextVar/маршрутизацію** — не для копіювання у прод.

> ⚠️ **Окремо: fall-through на невідомий Host = маршрут на master DB.**
>
> У прикладі нижче, якщо `domain is None` (тобто `Host`-header не збігається з жодним записом у `Domain`), middleware тихо пропускає запит із `current_tenant=None`, і router маршрутизує його на `default` (= master DB).
>
> Реальні наслідки:
>
> - Атакуючий може бити з довільним `Host: random.example.com` → платформенні view'и (admin, health, login) стають доступні з будь-якого Host'а. Підробка `Host` — типова reconnaissance-вектор.
> - Якщо колись з'явиться платформенний endpoint, що не перевіряє origin/host явно, він буде «безкоштовно» відкритий.
>
> **У реальній системі обов'язково треба явний allowlist платформенних хостів** (наприклад, `PLATFORM_HOSTS = {"app.example.com", "admin.example.com"}`), і всі решта Host'ів — `raise Http404` ще до `get_response`. Сам код middleware у прикладі для лаконічності цього не робить, але у прод-коді це not optional.

```python
# tenants/middleware.py
from tenants.models import Domain
from tenants.routing.context import current_tenant
from tenants.routing.registry import ensure_tenant_db_registered


class TenantDBMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0]
        
        domain = (
            Domain.objects.using("default")
            .select_related("tenant")
            .filter(domain=host)
            .first()
        )
        
        if domain is None or domain.tenant.schema_name == "public":
            token = current_tenant.set(None)
            try:
                return self.get_response(request)
            finally:
                current_tenant.reset(token)
        
        ensure_tenant_db_registered(domain.tenant.schema_name)
        token = current_tenant.set(domain.tenant.schema_name)
        try:
            return self.get_response(request)
        finally:
            current_tenant.reset(token)
```

#### 3.3.7 Celery-інтеграція: tenant в task headers, signal-based context

**Чому**: `tenant-schemas-celery` робить це для schema_context, але у DB-per-tenant потрібна власна логіка через ContextVar.

> ⚠️ **Працює тільки під `--pool=prefork` (або `--pool=solo`).**
>
> Реалізація нижче зберігає `ContextVar.Token` як атрибут `task._tenant_token` на task-instance. У Celery task — це **singleton, зареєстрований у `app.tasks`** на старті процесу. У prefork один процес виконує task'и **серіально**, тож атрибут безпечно перезаписувати між запусками.
>
> Під `--pool=threads` (або gevent з ефективною greenlet-local'ьністю) кілька execution-юнітів одночасно виконують task'и одного класу і **переписують `task._tenant_token` одне одному**. На `task_postrun` ContextVar.reset отримає чужий токен → `ValueError: <Token> was created in a different Context` і race condition у маршрутизації.
>
> Якщо потрібен thread/greenlet pool — токен має зберігатися у scope, що не shared (наприклад, у самому `ContextVar`-stack'у через `Context.run()`-wrapping, або у dict, keyed по `task.request.id`).



```python
# tenants/celery_integration.py
from celery.signals import before_task_publish, task_prerun, task_postrun

from tenants.routing.context import current_tenant
from tenants.routing.registry import ensure_tenant_db_registered

HEADER_KEY = "_tenant_schema"


@before_task_publish.connect
def attach_tenant_header(headers=None, **kwargs):
    if headers is None:
        return
    schema = current_tenant.get()
    if schema:
        headers[HEADER_KEY] = schema


@task_prerun.connect
def set_tenant_from_header(task_id=None, task=None, **kwargs):
    headers = getattr(task.request, "headers", None) or {}
    schema = headers.get(HEADER_KEY)
    if schema:
        ensure_tenant_db_registered(schema)
        token = current_tenant.set(schema)
    else:
        token = current_tenant.set(None)
    task._tenant_token = token


@task_postrun.connect
def reset_tenant_after_task(task_id=None, task=None, **kwargs):
    # Чому ловимо тут і ТІЛЬКИ тут (без окремого task_failure handler'а):
    # `task_postrun` Celery шле з блоку finally у celery/app/trace.py
    # (функція `build_tracer` → `trace_task`), тобто **і на успіх, і на
    # exception, і на retry**. Окремий хендлер на `task_failure` зробив би
    # ContextVar.reset(token) ДВІЧІ для того ж токена на failure-шляху, що
    # підняло б `ValueError: Token <...> has already been used once`.
    # Джерела:
    #   - Celery docs «task_postrun»:
    #     https://docs.celeryq.dev/en/stable/userguide/signals.html#task-postrun
    #     («Dispatched after a task has been executed.»)
    #   - source: celery/app/trace.py — `send_postrun = task_postrun.send` у
    #     finally-блоці, незалежно від результату try-блоку.
    token = getattr(task, "_tenant_token", None)
    if token is not None:
        # Знімаємо атрибут одразу — щоб повторний випадковий хендлер (canvas
        # subtask, що ділить task-instance) не натрапив на той самий токен.
        task._tenant_token = None
        current_tenant.reset(token)
```

#### 3.3.8 `bootstrap_tenant` команда

> ⚠️ **Цей фрагмент — приклад скелету, а не drop-in production-код.** Перед використанням треба усвідомлено вирішити три відомі проблеми:
>
> 1. **Order-of-operations / orphaned row.** Майстер-INSERT комітається до `CREATE DATABASE`. Якщо `CREATE DATABASE` упаде (немає `template_db`, немає прав `CREATEDB`, диск повний), у `public` лишиться `Tenant`/`Domain`/`DBConfig`-рядок, що вказує на неіснуючу БД, і всі подальші registry-операції на цей `schema_name` падатимуть назавжди. Варіанти фіксу: (а) переставити порядок — спочатку `CREATE DATABASE`, потім INSERT; або (б) обернути блоки в `try` і робити компенсуючий `DROP DATABASE` + видалення master-рядка при помилці.
>
> 2. **Привілеї першого `company_admin`.** Нижче виставлено `is_superuser=True` для зручності демо. У реальному прод-сетапі це **anti-pattern** — Django-`is_superuser` обходить **усю** permission-матрицю DRF/Django, тобто рольовий розподіл (`Role.COMPANY_ADMIN`/`DRIVER`/`CUSTOMER`) у нашій моделі перестає мати значення. Має бути `is_superuser=False`, `is_staff=True` (якщо потрібен Django admin), а доступ контролюється через `role` + ваші permission-класи.
>
> 3. **Pre-migrated template-БД.** Виклик `create_user(...)` одразу після `CREATE DATABASE ... TEMPLATE template_tenant_clean` спрацює лише якщо `template_tenant_clean` уже має накатані міграції tenant-app'ів (у тому числі `users_user`-таблицю). Інакше — `ProgrammingError: relation "users_user" does not exist`. Або задокументувати процедуру підготовки template (`createdb template_tenant_clean && migrate --database=<alias>`), або вставити `call_command("migrate", database=alias, ...)` між `CREATE DATABASE` і `create_user`.

```python
# tenants/management/commands/bootstrap_tenant.py
import getpass
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from psycopg import sql

from tenants.models import Tenant, Domain, DBConfig
from tenants.routing.registry import ensure_tenant_db_registered
from users.models import User


# Дозволяємо лише латиницю/цифри/підкреслення для schema-name (а отже й
# для derived db_name, template-db, db-user). Це наш перший шар захисту;
# другий — psycopg.sql.Identifier у самому CREATE DATABASE.
_SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")

# ENV-var, з якого можна передати admin-password в CI/automation без
# попадання у command line. У інтерактивному запуску — getpass.getpass().
_ADMIN_PASSWORD_ENV = "TENANT_ADMIN_PASSWORD"


def _check_identifier(value: str, field: str) -> None:
    if not _SAFE_IDENTIFIER.match(value):
        raise CommandError(
            f"'{field}' must match {_SAFE_IDENTIFIER.pattern!r}; got {value!r}"
        )


class Command(BaseCommand):
    help = "Create new tenant DB and bootstrap first company_admin."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--domain", required=True)
        parser.add_argument("--admin-username", default="admin")
        # Пароль НЕ передаємо як CLI-аргумент: argv видно у `ps aux`,
        # /proc/<pid>/cmdline, у shell-history і часто у syslog'у при
        # auditd. Дві альтернативи:
        #   - ENV (для CI):  TENANT_ADMIN_PASSWORD=... manage.py bootstrap_tenant ...
        #   - getpass-prompt: запитує при інтерактивному запуску.
        parser.add_argument("--db-host", required=True)
        parser.add_argument("--db-user", required=True)
        parser.add_argument("--secret-arn", required=True)
        parser.add_argument("--template-db", default="template_tenant_clean")

    def _resolve_admin_password(self) -> str:
        # Пріоритет: env > prompt. Жодного --admin-password у argv.
        pw = os.environ.get(_ADMIN_PASSWORD_ENV)
        if pw:
            return pw
        pw = getpass.getpass(f"Admin password (or set ${_ADMIN_PASSWORD_ENV}): ")
        if not pw:
            raise CommandError("Admin password is required")
        return pw

    def handle(self, *args, **opts):
        schema = opts["schema"].lower()
        if schema == "public":
            raise CommandError("'public' is reserved")

        admin_password = self._resolve_admin_password()

        # Валідація identifier-полів, що далі підуть у DDL.
        _check_identifier(schema, "--schema")
        _check_identifier(opts["template_db"], "--template-db")
        _check_identifier(opts["db_user"], "--db-user")

        if Tenant.objects.filter(schema_name=schema).exists():
            raise CommandError(f"Tenant '{schema}' already exists")

        db_name = f"tenant_{schema}"

        # 1) Master-row INSERT — атомарно.
        with transaction.atomic(using="default"):
            tenant = Tenant.objects.create(schema_name=schema, name=opts["name"])
            Domain.objects.create(domain=opts["domain"], tenant=tenant, is_primary=True)
            DBConfig.objects.create(
                tenant=tenant,
                db_name=db_name,
                db_host=opts["db_host"],
                db_user=opts["db_user"],
                secret_arn=opts["secret_arn"],
            )

        # 2) CREATE DATABASE — НЕ можна у транзакції; default connection
        #    в autocommit-mode (бо ATOMIC_REQUESTS=False у нашому registry).
        #    Безпечна інтерполяція identifier'ів — через psycopg.sql.
        with connections["default"].cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE DATABASE {db} TEMPLATE {tpl} OWNER {own}"
                ).format(
                    db=sql.Identifier(db_name),
                    tpl=sql.Identifier(opts["template_db"]),
                    own=sql.Identifier(opts["db_user"]),
                )
            )

        # 3) Реєстрація alias і створення першого company_admin.
        alias = ensure_tenant_db_registered(schema)
        User.objects.using(alias).create_user(
            username=opts["admin_username"],
            password=admin_password,
            role=User.Role.COMPANY_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.stdout.write(self.style.SUCCESS(f"Tenant '{schema}' ready"))
```

#### 3.3.9 Migration orchestrator — fan-out міграцій

```python
# tenants/management/commands/migrate_tenants.py
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from django.core.management import call_command
from django.core.management.base import BaseCommand

from tenants.models import DBConfig
from tenants.routing.registry import ensure_tenant_db_registered


class Command(BaseCommand):
    help = "Run Django migrations against all tenant databases."

    def add_arguments(self, parser):
        parser.add_argument("--parallel", type=int, default=1)
        parser.add_argument("--schemas", nargs="*")

    def handle(self, *args, **opts):
        targets = opts["schemas"] or list(
            DBConfig.objects.using("default")
            .select_related("tenant")
            .values_list("tenant__schema_name", flat=True)
        )
        
        if opts["parallel"] == 1:
            results = [(s, _migrate_one(s)) for s in targets]
        else:
            results = []
            # ВАЖЛИВО: mp_context="spawn".
            # На Linux ProcessPoolExecutor за дефолтом форкає процеси. На момент
            # форку Django вже ініціалізований і може тримати ВІДКРИТІ TCP-сокети
            # до default (master) DB. fork() копіює file descriptor'и → діти
            # успадковують ТОЙ САМИЙ socket, на який паралельно пишуть libpq
            # у різних процесах → SSL/TLS state corruption. Симптом — random
            # `SSL error: decryption failed or bad record mac`, `bad message length`,
            # `unexpected EOF` під час паралельних міграцій. Reproducible лише під
            # навантаженням, тож unit-тести цього не зловлять.
            # spawn створює свіжий Python interpreter без inherited FD'ів —
            # дитина запускає django.setup() з нуля, з'єднання нові.
            spawn_ctx = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=opts["parallel"], mp_context=spawn_ctx,
            ) as ex:
                futures = {ex.submit(_migrate_one, s): s for s in targets}
                for fut in as_completed(futures):
                    results.append((futures[fut], fut.result()))
        
        ok = [s for s, r in results if r is None]
        fail = [(s, e) for s, e in results if e is not None]
        self.stdout.write(self.style.SUCCESS(f"OK: {len(ok)}"))
        if fail:
            for s, e in fail:
                self.stdout.write(self.style.ERROR(f"  {s}: {e}"))
            sys.exit(1)


def _migrate_one(schema_name):
    try:
        alias = ensure_tenant_db_registered(schema_name)
        call_command("migrate", database=alias, interactive=False, verbosity=0)
        return None
    except Exception as exc:
        return repr(exc)
```

#### 3.3.10 Async-aware middleware — для phase 2

> ⚠️ Обидва застереження з §3.3.6 (DB-lookup на кожен запит ОБОВ'ЯЗКОВО кешувати + fall-through на невідомий Host = маршрут на master) **повністю стосуються і цього async-варіанту**. Він має ту саму ваду на read-path'і — просто async-flavored через `.afirst()`. Перед прод-використанням переглянь обидві ⚠️-врізки у §3.3.6 і застосуй ті ж самі fix'и (кеш + Host allowlist).

```python
# tenants/middleware_async.py
from asgiref.sync import sync_to_async

from tenants.models import Domain
from tenants.routing.context import current_tenant
from tenants.routing.registry import ensure_tenant_db_registered


class TenantDBAsyncMiddleware:
    async_capable = True
    sync_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    async def __call__(self, request):
        host = request.get_host().split(":")[0]
        
        domain = await (
            Domain.objects.using("default")
            .select_related("tenant")
            .filter(domain=host)
            .afirst()
        )
        
        if domain is None or domain.tenant.schema_name == "public":
            token = current_tenant.set(None)
            try:
                return await self.get_response(request)
            finally:
                current_tenant.reset(token)
        
        await sync_to_async(
            ensure_tenant_db_registered, thread_sensitive=True,
        )(domain.tenant.schema_name)
        
        token = current_tenant.set(domain.tenant.schema_name)
        try:
            return await self.get_response(request)
        finally:
            current_tenant.reset(token)
```

#### 3.3.11 PgBouncer config для DB-per-tenant

> **Перед стартом** PgBouncer'а на master DB треба створити SQL-функцію,
> яку він використовує для auth-lookup'у (`auth_query` нижче). Без неї
> отримаєш у логах `ERROR: function pgbouncer_auth(text) does not exist`
> і всі клієнти відвалюватимуться з `auth failed`.

```sql
-- Виконати на master DB (одноразово, як superuser або власник).
-- Функція дозволяє непривілейованому pgbouncer-user'ові читати hash'і
-- паролів з pg_shadow, не маючи прямого SELECT-доступу до pg_shadow.

CREATE OR REPLACE FUNCTION pgbouncer_auth(p_username text)
RETURNS TABLE(username text, password text)
LANGUAGE plpgsql
SECURITY DEFINER     -- виконується від імені власника функції
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN QUERY
    SELECT usename::text, passwd::text
    FROM pg_shadow
    WHERE usename = p_username;
END;
$$;

-- Дозволити викликати ЛИШЕ pgbouncer-user'ові:
REVOKE ALL ON FUNCTION pgbouncer_auth(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pgbouncer_auth(text) TO pgbouncer_role;
-- (pgbouncer_role — окрема PG-роль, від якої PgBouncer ходить за auth.)
```

> ⚠️ **Узгодити формат паролів із `auth_type`.**
>
> `pg_shadow.passwd` повертає той формат, у якому користувача створили
> чи останній раз робили `ALTER USER ... PASSWORD ...`. PgBouncer
> із `auth_type = scram-sha-256` (як нижче) очікує SCRAM-форматований hash.
> Якщо хоч один tenant-user був створений за legacy
> `password_encryption = md5`, PgBouncer відмовить його запитам:
> `client auth failed: password does not match`.
>
> Перевірити поточну установку на cluster'і:
>
> ```sql
> SHOW password_encryption;
> -- очікуємо: scram-sha-256
> ```
>
> Якщо `md5` — змінити через cluster parameter group (як у §3.5.6 для
> `idle_session_timeout`) і перестворити паролі всіх tenant-users:
>
> ```sql
> -- виконати ПІСЛЯ зміни password_encryption на scram-sha-256
> ALTER USER tenant_alpha_user PASSWORD 'same-as-before';  -- re-encode
> ```
>
> На свіжому проєкті (Aurora PG 14+) дефолт уже `scram-sha-256`, тож
> зазвичай нічого додатково робити не треба — це застереження для
> legacy-clusters і мігруючих setup'ів.

```ini
# /etc/pgbouncer/pgbouncer.ini
[databases]
* = host=tenants-cluster.cluster-XYZ.us-east-2.rds.amazonaws.com port=5432

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = scram-sha-256
# auth_file використовується як fallback, якщо auth_query (нижче) недоступний —
# наприклад, master DB тимчасово down. Тримати в ньому тільки emergency-user'а
# для admin-доступу, не основних tenant-користувачів.
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
default_pool_size = 5
max_db_connections = 30
reserve_pool_size = 3
reserve_pool_timeout = 5
server_idle_timeout = 60
server_lifetime = 3600
client_idle_timeout = 0
max_client_conn = 5000
query_wait_timeout = 30

ignore_startup_parameters = extra_float_digits,search_path,application_name
auth_query = SELECT username, password FROM pgbouncer_auth($1)
```

#### 3.3.12 Cache invalidation через Redis pub/sub

**Навіщо**: Per-worker cache має 5-хвилинний TTL із версією за `DBConfig.updated_at`. У більшості випадків цього вистачає. Але є три сценарії, де 5 хвилин — задовго: ротація credentials, move tenant до іншого cluster'а, tenant deactivation. TTL-based вирішує повільно; connection-failure retry — лізо; Redis pub/sub — майже моментально (~msec).

**Як працює**: Redis `PUBLISH`/`SUBSCRIBE`. Один процес-воркер тримає subscriber thread, що слухає Redis CHANNEL. Producer публікує — Redis fan-out'ить всім; кожен subscriber викликає `invalidate_tenant()` локально.

**Коли запускати**: один subscriber на процес-воркер, у `wsgi.py`/`asgi.py`/`celery_app.py` через `worker_init`.

**Subscriber + publisher**:

```python
# tenants/routing/invalidator.py
"""
Cache invalidation через Redis pub/sub.

Один module-level redis-клієнт обслуговує і subscriber, і publisher через
свій внутрішній connection pool:
  - subscriber: `_redis.pubsub()` бере одне connection із pool'у і тримає
    його у subscribe-режимі для `listen()`.
  - publisher: `_redis.publish(...)` бере інше connection із того ж pool'у
    для команди — pubsub не блокує інші команди на рівні pool'у.

Жодних `redis.from_url(...)` всередині функцій: інакше publisher створював би
новий TCP-socket на кожен виклик.
"""
import logging
import threading
import time

import redis
from django.conf import settings

from tenants.routing.registry import invalidate_tenant

logger = logging.getLogger(__name__)

CHANNEL = "tenant_cache_invalidate"

# Module-level singleton. `redis.from_url()` не відкриває з'єднання, поки
# не виконається перша команда — імпорт безпечний навіть коли Redis down.
_redis = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_keepalive=True,
    health_check_interval=30,
)

_subscriber_thread: threading.Thread | None = None
_subscriber_lock = threading.Lock()


def start_invalidator() -> threading.Thread:
    """Запустити subscriber у фоновому threadʼі. Повторні виклики no-op."""
    global _subscriber_thread
    with _subscriber_lock:
        if _subscriber_thread is not None and _subscriber_thread.is_alive():
            return _subscriber_thread
        _subscriber_thread = threading.Thread(
            target=_subscriber_loop,
            daemon=True,
            name="tenant-invalidator",
        )
        _subscriber_thread.start()
        return _subscriber_thread


def _subscriber_loop() -> None:
    backoff = 1
    while True:
        try:
            pubsub = _redis.pubsub()
            pubsub.subscribe(CHANNEL)
            backoff = 1
            for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    invalidate_tenant(msg["data"])
                except Exception:
                    logger.exception("invalidate failed for %s", msg["data"])
        except redis.ConnectionError:
            logger.warning("Redis disconnected, reconnect in %ds", backoff)
        except Exception:
            logger.exception("invalidator unexpected error")
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)


def publish_invalidation(schema_name: str) -> None:
    """Опублікувати invalidation message; subscriber'и в усіх воркерах отримають."""
    _redis.publish(CHANNEL, schema_name)
```

**Auto-publish через signal на `DBConfig`**:

```python
# tenants/signals.py
import logging

from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from tenants.models import DBConfig
from tenants.routing.invalidator import publish_invalidation

logger = logging.getLogger(__name__)


@receiver([post_save, post_delete], sender=DBConfig)
def invalidate_on_dbconfig_change(sender, instance, **kwargs):
    # Дві небезпеки, які треба ізолювати від основного save():
    #
    # 1) post_save сигнал летить ВСЕРЕДИНІ транзакції, до commit. Якщо
    #    публікуємо invalidation у момент сигналу, subscriber'и можуть
    #    почати invalidate cache раніше, ніж committed дані стануть видимі
    #    іншим процесам. transaction.on_commit() гарантує, що публікація
    #    стається лише ПІСЛЯ успішного commit.
    #
    # 2) Redis може бути недоступний. Якщо publish() кине ConnectionError,
    #    він пробиває назовні і save() вважається failed для caller'а —
    #    хоча запис у БД уже committed. Інконсистенція + дивний 500 у юзера.
    #    Тож обгортаємо у try/except і логуємо. У production такий exception
    #    має тригерити alert (cache потенційно stale), але НЕ ламати запис.
    schema_name = instance.tenant.schema_name

    def _publish_safely():
        try:
            publish_invalidation(schema_name)
        except Exception:
            logger.exception(
                "publish_invalidation failed for schema=%s — cache may be stale "
                "до TTL-expiry (%ds)", schema_name, 300,
            )

    transaction.on_commit(_publish_safely)
```

Підключити у `apps.py`:

```python
# tenants/apps.py
from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = "tenants"

    def ready(self):
        from . import signals  # noqa: F401
```

**Запуск subscriber'а у `wsgi.py`/`asgi.py`/Celery**:

```python
# project/wsgi.py
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
application = get_wsgi_application()

from tenants.routing.invalidator import start_invalidator
start_invalidator()
```

```python
# project/celery_app.py
from celery import Celery
from celery.signals import worker_init

app = Celery("project")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

import tenants.celery_integration  # noqa: F401


@worker_init.connect
def start_tenant_invalidator(**kwargs):
    from tenants.routing.invalidator import start_invalidator
    start_invalidator()
```

### 3.4 Закривати чи не закривати connection після request'у

#### 3.4.1 Чотири стратегії

**Перше уточнення — дві ортогональні осі.** «Client connection lifetime»
(Django `CONN_MAX_AGE`) і «backend pool mode» (PgBouncer
`session`/`transaction`/`statement`) — це **незалежні** характеристики,
які часто плутають. Persistent client connection до PgBouncer у
transaction-mode — це **штатний патерн**, заради якого пулер і існує:
client тримає одне довге TCP-з'єднання, PgBouncer мультиплексує його на
пул backend-з'єднань per-transaction. Сумісність обмежена не client
lifetime'ом, а **session-state caveats** з §3.2.5 (prepared statements,
`SET TIMEZONE`, session-scope advisory locks, LISTEN/NOTIFY,
`SET search_path` — критичне для schema-варіанту, нерелевантне для нас).

| Стратегія                                 | CONN_MAX_AGE | Що відбувається                                  | Latency hot path | Cached connections per worker |
|-------------------------------------------|--------------|--------------------------------------------------|------------------|-------------------------------|
| A. Нескінченно persistent                  | `None`       | Connection живе стільки, скільки живе процес     | ~0ms             | Необмежене зростання          |
| B. Aggressive close (= Django default)     | `0`          | Connection закривається в кінці request'у        | +1-3ms           | Низький (тільки in-flight)    |
| C. TTL-based                               | `N` сек      | Connection живе N сек, потім Django сам закриває  | ~0ms hot         | Обмежений TTL'ом              |
| D. Per-tenant smart LRU eviction           | `N` + LRU    | Тримаємо top-K hot, інші вибиваємо явно           | ~0ms hot         | Bounded by K                  |

> **Поправка на типову плутанину:** Django *default* — це **стратегія B**
> (`CONN_MAX_AGE=0`, close after request). «Persistent» (`>0` або `None`)
> треба прописати в `DATABASES[<alias>]` явно — це **не** дефолт.

#### 3.4.2 У DB-per-tenant із PgBouncer/RDS Proxy

**Стратегію A (`None`) — НЕ використовуємо.** Причина — **не**
«несумісність» з transaction-mode пулером (її немає, якщо caveats з
§3.2.5 розв'язані), а дві **операційні** проблеми, специфічні саме для
DB-per-tenant контексту:

1. **Unbounded memory growth у per-worker registry.** Registry кешує по
   `DatabaseWrapper`-обʼєкту на кожного «торкнутого» тенанта. Без
   TTL/eviction worker, що за рік торкнеться 5 000 тенантів, утримує
   5 000 wrapper'ів × ~5 КБ ≈ **25 МБ на сам тільки кеш**, на КОЖЕН
   процес. На k8s pod із 256 МБ memory limit це 10% бюджету, віддане ні
   на що.
2. **Накопичення stale connections.** Connection, який NAT-gateway /
   PgBouncer `client_idle_timeout` / Aurora `idle_session_timeout` тихо
   обірвали вночі, лишається в кеші Python-side. Перший ранковий запит
   → `OperationalError`. `CONN_HEALTH_CHECKS=True` ловить це майже
   завжди (`SELECT 1` перед reuse), але без TTL/eviction число
   «потенційно мертвих» connection'ів росте, і витрати на health-check
   ростуть з ним.

Для **schema-per-tenant** (не наш випадок) є **третя**, справді
блокуюча причина: маршрутизація через `SET search_path` — це
session-state, що губиться між транзакціями у transaction-mode. Звідти,
ймовірно, і виник міф «persistent + transaction-mode = біда». У нас
цього не виникає — маршрутизація через DB alias, кожна tenant-БД — це
окремий `dbname` для пулера.

**Дефолт для типового SaaS-навантаження зі скошеним трафіком (1000+
тенантів, top-10 = 60%+ трафіку) — стратегія D (LRU eviction).**
Обґрунтування у відповідному блоку нижче. Стратегії B і C тут — як
простіші fallback'и для менш типових сценаріїв (мало тенантів, рівний
трафік, або setup без PgBouncer'а).

**Стратегія B (`CONN_MAX_AGE=0`, close after request)** — найпростіший
варіант. Підходить, коли тенантів небагато (десятки), скос трафіку
відсутній, і connect-cost через пулер прийнятний:

```python
# tenants/middleware_close.py
from django.db import connections

from tenants.routing.context import current_tenant


class CloseTenantConnectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        schema = current_tenant.get()
        if schema:
            alias = f"tenant_{schema}"
            if alias in connections._connections:
                try:
                    connections[alias].close()
                except Exception:
                    pass
        return response
```

**Стратегія C (TTL-based) — окремого коду не потребує.** Це чиста
конфігурація, не middleware: Django сам після завершення request'у
дивиться `time.monotonic() - connection.close_at` і закриває
з'єднання, якщо вік перевищив `CONN_MAX_AGE`. Все, що треба для C, уже
є у `_register_or_refresh` (§3.3.4):

```python
"CONN_MAX_AGE": 600,          # 10 хв TTL
"CONN_HEALTH_CHECKS": True,   # SELECT 1 перед reuse, ловить stale
```

Reference: `django/db/backends/base/base.py` — `BaseDatabaseWrapper.close_if_unusable_or_obsolete()` (викликається з `django.db.close_old_connections`, що проганяється `request_started` / `request_finished` signal handler'ами).

Тобто стратегія C — це «не робимо нічого додатково, лишаємо TTL з
registry». Окрема стратегія D **поверх** цього додає LRU-обмеження
кількості одночасно кешованих з'єднань — корисно, коли тенантів багато
й TTL'у недостатньо, щоб тримати кеш у межах.

**Стратегія D (LRU eviction over TTL'd connections)** — обирається,
коли профіль трафіку **сильно скошений** (top-10 тенантів дають 60%+
запитів) і коли cost reconnect'у на cold tenant'ів через PgBouncer уже
відчувається у p95. Підтримуємо bounded top-K cache: hot tenant'и не
платять за reconnect, cold — вибиваються.

> Код нижче використовує приватне Django-API (`connections._connections`). Public-API еквівалент — у **§3.7.3** (різниця — `~5KB` wrapper-памʼяті per tenant залишається у кеші, але без залежності від внутрішнього атрибута Django).

```python
# tenants/routing/eviction.py
"""
LRU eviction: тримати не більше N кешованих connections per worker process.
При перевищенні — закривати найдавніший.
"""
import time
import threading
from collections import OrderedDict

from django.db import connections

_lru: OrderedDict[str, float] = OrderedDict()
_lock = threading.Lock()
_MAX_CACHED = 50


def touch(alias: str) -> None:
    """Позначити alias як 'нещодавно використаний'.

    Працює і для нового alias (просто додає), і для існуючого (рухає в кінець).
    NB: OrderedDict.move_to_end(key) піднімає KeyError, якщо ключа немає,
    тому перевіряємо `in _lru` перш ніж викликати.
    """
    with _lock:
        if alias in _lru:
            _lru.move_to_end(alias)
        _lru[alias] = time.time()
        while len(_lru) > _MAX_CACHED:
            oldest_alias, _ = _lru.popitem(last=False)
            if oldest_alias in connections._connections:
                try:
                    connections[oldest_alias].close()
                except Exception:
                    pass
                connections._connections.pop(oldest_alias, None)
```

```python
# tenants/middleware_lru.py
from tenants.routing.context import current_tenant
from tenants.routing.eviction import touch


class TenantLRUTouchMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        schema = current_tenant.get()
        if schema:
            touch(f"tenant_{schema}")
        return response
```

> Стратегії B і D — взаємовиключні **в межах одного tier'у** (web ABO Celery — обирай одне). Між tier'ами можна мікшувати: типовий прод-setup — D на web (`TenantLRUTouchMiddleware`) + B на Celery (`task_postrun closing`). Саме така комбінація рекомендована у §3.5.7.

#### 3.4.3 Celery worker'и

```python
# tenants/celery_close.py — стратегія B для Celery
from celery.signals import task_postrun
from django.db import connections


@task_postrun.connect
def close_tenant_conn_after_task(task_id=None, task=None, **kwargs):
    headers = getattr(task.request, "headers", None) or {}
    schema = headers.get("_tenant_schema")
    if schema:
        alias = f"tenant_{schema}"
        if alias in connections._connections:
            try:
                connections[alias].close()
            except Exception:
                pass
```

```python
# tenants/celery_lru.py — стратегія D для Celery
from celery.signals import task_postrun

from tenants.routing.eviction import touch


@task_postrun.connect
def touch_after_task(task_id=None, task=None, **kwargs):
    headers = getattr(task.request, "headers", None) or {}
    schema = headers.get("_tenant_schema")
    if schema:
        touch(f"tenant_{schema}")
```

#### 3.4.4 Рекомендація

Для setup'у з 1000 тенантів і скосом top-10 = 60%:

- **Web tier**: `TenantLRUTouchMiddleware` (D)
- **Celery**: `task_postrun` із `touch_after_task`
- **Master connection** (`DATABASES["default"]`): стратегія **C** — `CONN_MAX_AGE = 600` + `CONN_HEALTH_CHECKS = True`. Persistent на 10 хв, з health-check'ом перед reuse. Без LRU — master один, eviction-pressure'у не виникає.

### 3.5 «Протухання» connection'ів — детектування і відновлення

#### 3.5.1 Природа проблеми

TCP socket між Django process'ом і пулером може дропнутись через:

1. NAT/firewall idle timeout (AWS NAT Gateway — 350с)
2. Aurora `idle_session_timeout`
3. PgBouncer `server_idle_timeout` (default 600s)

#### 3.5.2 Захист на рівні Django: `CONN_HEALTH_CHECKS`

```python
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
```

Django 4.1+: **перед reuse persistent connection** (на початку нового
request'у/task'у) виконує `connection.is_usable()` (тривіальний `SELECT 1`).
Якщо падає — закриває і відкриває нову. Cost: +1-3ms на reuse.

> **Важливо**: ця опція має сенс **тільки разом із `CONN_MAX_AGE > 0`**.
> Якщо `CONN_MAX_AGE=0`, Django закриває connection після кожного
> request'у — наступний завжди свіжий, health check не потрібний і
> фактично no-op. У §3.3.4 виставлено `CONN_MAX_AGE=600`, тому
> `CONN_HEALTH_CHECKS=True` має ефект.

#### 3.5.3 TCP keepalive

```python
"OPTIONS": {
    "sslmode": "require",
    "connect_timeout": 5,
    "options": "-c statement_timeout=30000",
    "prepare_threshold": None,
    "keepalives": 1,
    "keepalives_idle": 60,
    "keepalives_interval": 10,
    "keepalives_count": 5,
},
```

#### 3.5.4 Retry-on-OperationalError

```python
# tenants/db_retry.py
import functools

from django.db import connections
from django.db.utils import OperationalError  # ← Django-обгортка, НЕ psycopg.OperationalError

from tenants.routing.context import current_tenant


# ВАЖЛИВО: треба ловити саме `django.db.utils.OperationalError`.
# Django ORM проганяє кожен виклик через `Database._wrap_database_errors`,
# який переловлює `psycopg.OperationalError` і перекидає вже у власному
# класі (`django.db.utils.OperationalError`, що походить від
# `django.db.utils.DatabaseError`). На рівні view/Celery-task до тебе
# долітає саме Django-варіант — psycopg-варіант не пройде повз цей except.
# Reference: django/db/utils.py → `DatabaseErrorWrapper.__exit__` та
# django/db/backends/utils.py → `CursorWrapper._execute_with_wrappers`.
#
# ВАЖЛИВО-2: `OperationalError` — широкий клас. У нього потрапляють і
# справді stale-connection-сценарії (NAT-drop, pgbouncer kicked us,
# Aurora idle_session_timeout), і нерелевантні випадки (deadlock,
# query cancellation, statement_timeout, server crash). Сліпий retry
# по будь-якому OperationalError призводить до:
#   - дублюючих side-effects, якщо view вже встиг щось зробити;
#   - retry deadlock'у замість його ескалації;
#   - маскування справжніх багів.
# Тому треба диференціювати «втратили з'єднання» від «з'єднання живе,
# але запит фейлиться» — наприклад, через psycopg SQLSTATE (pgcode):
#
#   STALE_PGCODES = {
#       "08000",  # connection_exception
#       "08003",  # connection_does_not_exist
#       "08006",  # connection_failure
#       "08001",  # sqlclient_unable_to_establish_sqlconnection
#       "08004",  # sqlserver_rejected_establishment_of_sqlconnection
#       "57P01",  # admin_shutdown
#       "57P02",  # crash_shutdown
#       "57P03",  # cannot_connect_now
#   }
#
#   def _is_stale(exc: Exception) -> bool:
#       # Django зберігає оригінальний psycopg-exception у __cause__
#       inner = exc.__cause__ or exc
#       pgcode = getattr(inner, "sqlstate", None) or getattr(
#           getattr(inner, "diag", None), "sqlstate", None,
#       )
#       return pgcode in STALE_PGCODES
#
# Також: не ретраїти всередині явного `atomic()` — транзакція вже
# aborted, retry виконається у новій транзакції з нуля і може
# зламати інваріанти, які view сподівався тримати під одним lock'ом.


def retry_on_stale_connection(view):
    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except OperationalError as exc:
            # TODO(prod): замінити on `if not _is_stale(exc): raise` —
            # див. коментар вище.
            schema = current_tenant.get()
            alias = f"tenant_{schema}" if schema else "default"
            if alias in connections._connections:
                try:
                    connections[alias].close()
                except Exception:
                    pass
            return view(request, *args, **kwargs)
    return wrapped
```

Для CBV (DRF `APIView` / `ViewSet` / `GenericViewSet`) треба використовувати `method_decorator(retry_on_stale_connection, name='dispatch')` — Django-helper, що адаптує FBV-decorator до class-based view'у, обгортаючи метод `dispatch`.

#### 3.5.5 PgBouncer health check

**Доповни існуючий `[pgbouncer]`-блок із §3.3.11 такими ключами** (не створюй другу секцію — PgBouncer прочитає тільки останню):

```ini
# додаток до [pgbouncer] із §3.3.11
server_check_query = SELECT 1
server_check_delay = 30
server_lifetime = 3600
```

#### 3.5.6 Aurora idle_session_timeout

> **Потребує Aurora PostgreSQL 14+.** Параметр `idle_session_timeout`
> з'явився у PostgreSQL 14 (вересень 2021). На Aurora PostgreSQL 13.x і
> раніше його просто немає — `SHOW idle_session_timeout` поверне
> `ERROR: unrecognized configuration parameter`. Якщо ти на ≤13 — або
> апгрейдь cluster engine version, або покладайся виключно на pgbouncer
> `server_lifetime` (§3.5.5) і Django `CONN_HEALTH_CHECKS` (§3.5.2).

> **На Aurora `ALTER SYSTEM` не працює.** Команда `ALTER SYSTEM SET ...`
> вимагає superuser-прав, які AWS Aurora не видає клієнту (master-user
> у Aurora — не справжній PG superuser). Спроба отримає
> `permission denied to set parameter "idle_session_timeout"` або
> `must be superuser to execute ALTER SYSTEM command`.
>
> Aurora-параметри виставляються через **DB cluster parameter group**:

```bash
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name my-aurora-params \
  --parameters "ParameterName=idle_session_timeout,ParameterValue=900000,ApplyMethod=immediate"
```

Або через AWS Console: RDS → Parameter groups → твоя cluster-parameter group → редагуй `idle_session_timeout` (значення у мілісекундах, `900000` = 15 хв).

Перевірити, що значення застосувалось:

```sql
SHOW idle_session_timeout;
-- очікуваний вивід: 15min
```

#### 3.5.7 Сценарій: Celery worker + idle DB

Worker обслужив task для `delta` о 10:00, тримав connection. О 18:00 ловить новий task для `delta`. Без захисту — `OperationalError`. З `CONN_HEALTH_CHECKS=True` — `is_usable()` fails, Django відкриває новий. З `task_postrun` closing — connection не cached між task'ами.

**Рекомендована комбінація**:
1. `CONN_HEALTH_CHECKS=True`
2. `task_postrun` closing для Celery
3. `TenantLRUTouchMiddleware` для web
4. pgbouncer `server_check_query` + `server_lifetime`
5. TCP keepalive у OPTIONS

#### 3.5.8 Monitoring

| Метрика                                    | Що вказує                                              | Як зняти                                                   |
|--------------------------------------------|--------------------------------------------------------|------------------------------------------------------------|
| Tenant-aliases у `connections.databases`   | Скільки tenant DBConfig'ів зареєстрував цей worker     | `sum(1 for k in connections.databases if k.startswith("tenant_"))` — public API |
| Кешовані physical connections per worker   | Скільки фізичних socket'ів зараз відкрито              | `len(connections._connections)` (приватне API, §3.7) або власний counter у registry, якщо ідеш public-API шляхом |
| `pg_stat_activity` (Aurora-side)           | Реальна кількість backend connections                  | `SELECT state, count(*) FROM pg_stat_activity GROUP BY 1;` |
| Pgbouncer `SHOW POOLS`                     | Per-DB pool utilization                                | `psql -h pgbouncer -p 6432 pgbouncer -c 'SHOW POOLS'`      |
| Pgbouncer `server_pin` ratio               | Backend pinned (transaction-mode degradation)          | `SHOW POOLS` колонки `sv_active_cancel_req` тощо           |
| `OperationalError` rate                    | Frequency stale-connection recovery                    | app-метрики через `prometheus_client.Counter`              |
| Redis subscriber thread alive (per worker) | Чи живий invalidator                                   | `_subscriber_thread.is_alive()` + last-message timestamp   |

### 3.6 Резюме

| Шар                          | Рекомендоване                                                                              |
|------------------------------|--------------------------------------------------------------------------------------------|
| **Driver**                   | `psycopg[c]==3.2.3` (production), `psycopg[binary]` (dev)                                  |
| **Django**                   | 5.2.13. ORM має достатню async-підтримку для phase 2                                       |
| **Celery**                   | 5.4.0 + prefork pool. Власна signal-based інтеграція замість tenant-schemas-celery        |
| **Pooler**                   | RDS Proxy (managed) або PgBouncer у transaction-mode                                       |
| **Маршрутизація**            | `ContextVar` + custom `DATABASE_ROUTERS`. Async-compatible з day 1                         |
| **Registry**                 | Per-process `connections.databases` mutation + TTL cache + Redis pub/sub invalidation     |
| **Cache invalidation**       | Subscriber thread у кожному worker'і + `post_save` signal на DBConfig для auto-publish    |
| **Auth**                     | Aurora IAM tokens або Secrets Manager                                                      |
| **Connection lifecycle**     | Tenant-DBs: `TenantLRUTouchMiddleware` для hot/cold split (стратегія D). Master DB: `CONN_MAX_AGE=600` + `CONN_HEALTH_CHECKS=True` (стратегія C) |
| **Stale defense**            | `CONN_HEALTH_CHECKS=True` + TCP keepalive + pgbouncer `server_check_query` + retry-once    |
| **Migration**                | Власний fan-out command + PostgreSQL `CREATE DATABASE ... TEMPLATE` (файл-копія template-БД) |
| **Phase 2 (async/ASGI)**     | uvicorn[standard] + async middleware. Маршрутизація через ContextVar лишається             |

### 3.7 ⚠️ Увага! Варіант уникнення використання приватного API

Приклади у §3.3-§3.5 використовують `connections._connections.pop(alias)`
у 6 місцях для очищення кешованих DatabaseWrapper-обʼєктів. Це **приватний
Django-атрибут** (із підкресленням), що не покривається SemVer-гарантіями.

Цей підрозділ показує **повну альтернативу з використанням тільки
публічного Django-API**. Не потребує `_connections` ніде.

#### 3.7.1 Концепція

`connections._connections.pop(alias)` робить дві речі одночасно:

1. **Закриває фізичний socket** до Aurora.
2. **Видаляє `DatabaseWrapper`-обʼєкт** із per-thread cache (звільняє пам'ять).

Для пункту 1 існує публічний API — `connections[alias].close()`. Для
пункту 2 — публічного API нема.

Але якщо думати уважно: **wrapper memory cost ≈ 5KB per cached wrapper
per thread**. Для типового worker'а (1 thread у sync, 1 event loop у
async), якщо worker за життя торкнувся 1000 тенантів — це **5MB пам'яті**.
Прийнятно для будь-якої реалістичної конфігурації.

Тому альтернатива: **відмовитись від точки 2 повністю**, лишити тільки
`.close()`. Wrapper'и накопичуються, але обмежено загальною кількістю
тенантів у системі (бо worker не може торкнутися більше тенантів ніж їх
є).

Підводний камінь з registry: коли ми **оновлюємо config** для існуючого
alias (нові credentials після ротації), wrapper-обʼєкт тримає reference
на старий settings dict. Просто `close()` — wrapper при наступному
`connect()` візьме все ж таки старий dict. Розв'язується **in-place
мутацією** settings dict замість його заміни.

#### 3.7.2 `tenants/routing/registry.py` — public-API варіант

Базова архітектура — та сама, що у §3.3.4 (Option 1 pattern: fast path → slow I/O зовні локу → mutation під локом). Helper'и `_fetch_dbconfig`, `_build_config`, `_resolve_password`, `_get_secrets_client` — **без змін** від §3.3.4 (їх не наводимо повторно).

**Різниця тільки у блоці mutation:** замість `connections._connections.pop(alias, None)` + assignment'а нового dict'а — in-place мутація існуючого dict'а зі збереженням його identity (щоб wrapper, який лишається в кеші, побачив нові значення).

```python
def ensure_tenant_db_registered(schema_name: str) -> str:
    alias = f"tenant_{schema_name}"
    now = time.time()

    # ───── Fast path — без локу (ідентично §3.3.4) ─────
    cached = _meta.get(schema_name)
    if cached and (now - cached["ts"]) < _TTL_SECONDS and alias in connections.databases:
        return alias

    # ───── Slow I/O — ЗОВНІ локу (ідентично §3.3.4) ─────
    cfg = _fetch_dbconfig(schema_name)

    cached = _meta.get(schema_name)
    if (
        cached
        and alias in connections.databases
        and cached.get("version") == cfg.updated_at
    ):
        cached["ts"] = time.time()
        return alias

    password = _resolve_password(cfg)
    new_config = _build_config(cfg, password)

    # ───── Mutation only — public-API варіант ─────
    with _lock:
        # Final re-check (ідентично §3.3.4).
        cached = _meta.get(schema_name)
        if (
            cached
            and alias in connections.databases
            and cached.get("version") >= cfg.updated_at
        ):
            cached["ts"] = time.time()
            return alias

        if alias in connections.databases:
            # In-place мутація settings_dict зі збереженням ЙОГО IDENTITY.
            # Wrapper лишається в кеші (бо ми НЕ робимо connections._connections.pop)
            # і тримає reference саме на цей dict-обʼєкт. Тому in-place зміна
            # ВИДНА wrapper'у при наступному .connect().
            #
            # ВАЖЛИВО: НЕ використовуємо .clear() + .update().
            # .clear() створював би вікно порожнього dict'а — Django
            # get_connection_params() читає sequence з 7 ключів settings_dict
            # (NAME, OPTIONS, USER, PASSWORD, HOST, PORT тощо), і якщо
            # reader-thread потрапляє між нашим .clear() і .update() — він
            # ловить `KeyError: 'USER'` або подібний на пів-зачищеному dict'і.
            # Вікно мікроскопічне (~µs), але під concurrent навантаженням
            # ловиться.
            #
            # Правильний pattern — update first, then remove obsolete:
            # dict у будь-який момент часу містить АБО старий, АБО новий,
            # АБО mix значень — але НІКОЛИ не порожній.
            old_dict = connections.databases[alias]
            old_dict.update(new_config)                              # 1) overwrite існуючих
            obsolete = set(old_dict.keys()) - set(new_config.keys())  # 2) приберемо ті, що
            for k in obsolete:                                       #    більше не потрібні
                old_dict.pop(k, None)
            # Закриваємо physical socket, щоб наступний connect підняв
            # connection із новими credentials.
            try:
                connections[alias].close()
            except Exception:
                pass
        else:
            # Першу реєстрацію робимо звичайним assignment'ом — wrapper
            # ще не існує, identity-збереження не потрібне.
            connections.databases[alias] = new_config

        _meta[schema_name] = {"ts": time.time(), "version": cfg.updated_at}

    return alias


def invalidate_tenant(schema_name: str) -> None:
    """Очистити cache конкретного тенанта (тільки connection, не wrapper).

    На відміну від §3.3.4-варіанту, тут НЕ робимо connections._connections.pop:
    wrapper навмисно лишається (це вся суть public-API підходу). Закриваємо
    лише фізичний socket — наступний request підніме нову конекцію через
    той самий wrapper, який візьме поточні (можливо щойно оновлені) settings.
    """
    with _lock:
        _meta.pop(schema_name, None)
        alias = f"tenant_{schema_name}"
        if alias in connections.databases:
            try:
                connections[alias].close()
            except Exception:
                pass
```

#### 3.7.3 `tenants/routing/eviction.py` — public-API LRU touch

```python
def touch(alias: str) -> None:
    with _lock:
        if alias in _lru:
            _lru.move_to_end(alias)
        _lru[alias] = time.time()
        while len(_lru) > _MAX_CACHED:
            oldest_alias, _ = _lru.popitem(last=False)
            try:
                connections[oldest_alias].close()
            except Exception:
                pass
            # Wrapper-обʼєкт лишається в connections._connections (~5KB),
            # але physical socket звільнено.
```

#### 3.7.4 `tenants/middleware_close.py` — public-API close-after-request

```python
class CloseTenantConnectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        schema = current_tenant.get()
        if schema:
            try:
                connections[f"tenant_{schema}"].close()
            except Exception:
                pass
        return response
```

#### 3.7.5 `tenants/celery_close.py` — public-API close-after-task

```python
@task_postrun.connect
def close_tenant_conn_after_task(task_id=None, task=None, **kwargs):
    headers = getattr(task.request, "headers", None) or {}
    schema = headers.get("_tenant_schema")
    if schema:
        try:
            connections[f"tenant_{schema}"].close()
        except Exception:
            pass
```

#### 3.7.6 `tenants/db_retry.py` — public-API retry

```python
def retry_on_stale_connection(view):
    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except OperationalError:
            schema = current_tenant.get()
            alias = f"tenant_{schema}" if schema else "default"
            try:
                connections[alias].close()
            except Exception:
                pass
            return view(request, *args, **kwargs)
    return wrapped
```

#### 3.7.7 Що змінюється семантично

| Аспект                                    | З `_connections.pop` (приватне API)      | Public-API only (close)                          |
|--------------------------------------------|-------------------------------------------|--------------------------------------------------|
| Public Django API?                         | ❌ ні                                     | ✅ так                                            |
| Звільняє socket?                          | ✅                                        | ✅                                                |
| Звільняє wrapper-memory?                   | ✅                                        | ❌ wrapper лишається в cache                     |
| Працює при credential rotation?            | ✅ (новий wrapper із новим dict)         | ✅ (in-place mutation dict — той самий ефект)    |
| Працює при апгрейді Django 5.2 → 5.3 → 6.0 | ⚠️ залежить від внутрішньої стабільності | ✅ гарантовано (Django публічний contract)       |
| Memory cost per worker                     | O(LRU size)                               | O(distinct tenants touched ever) ≈ 5KB × N       |

Для **1000-tenant** проекту з worker'ом, що за рік торкнеться всіх — це
**5MB пам'яті per worker**. Менше за runtime overhead самого
Django-process'у.

#### 3.7.8 Коли все ж лишити `_connections.pop`

Один реалістичний кейс: **>10K тенантів** І **жорсткі memory-budget**
(наприклад, k8s pod із 256MB limit). 10K × 5KB = 50MB накладних — це вже
відчутно.

Тоді залишаємо `_connections.pop` із явним disclaimer-блоком у README і у
`requirements.txt`:

```
# pin Django по minor-version, бо tenants/routing/*.py покладається на
# connections._connections (приватний атрибут)
Django>=5.2,<5.3
```

#### 3.7.9 Підсумок вибору

| Сценарій                              | Що використовувати                                                |
|----------------------------------------|-------------------------------------------------------------------|
| Дефолтний (1000 тенантів, web+celery)  | **§3.7 — тільки `close()`** (public API, ~5MB накладних на worker) |
| Memory-tight (10K+ tenants, k8s)       | §3.3-§3.5 (з `_connections.pop`) + disclaimer про Django pin       |
| Major Django upgrade incoming          | §3.7 — closes-only variant                                         |

Якщо коли-небудь Django зробить публічний API для evict-from-cache
(наприклад `connections.evict(alias)`), §3.3-§3.5 і §3.7 зможуть
використати спільну реалізацію без trade-off'ів.

---

### 3.8 App, оголошений одночасно у `SHARED_APPS` і `TENANT_APPS`: інтерпретація у DB-per-tenant архітектурі

#### 3.8.1 Контекст і чому це окреме питання

У schema-per-tenant (canonical django-tenants) поширений патерн — оголосити
один Django-app у **обох** списках:

```python
SHARED_APPS = (
    "django_tenants",
    "tenants",
    "users",         # ← у обох
    ...
)
TENANT_APPS = (
    "users",         # ← у обох
    "orders",
    "drivers",
    ...
)
```

Класичний приклад — app `users`: platform-admin потрібен у `public`-схемі
(керує тенантами), tenant-local users (company_admin, driver, customer)
потрібні у кожній tenant-схемі. Один app, дві ролі.

У schema-per-tenant це працює природно — фізично є **одна БД**, у ній N+1
схем, і таблиця `users_user` існує у `public.users_user`,
`alpha.users_user`, `beta.users_user`. PG-resolution через `search_path`
обирає правильну на льоту: middleware виставив `search_path=alpha` →
`SELECT … FROM users_user` потрапляє у `alpha.users_user`.

У DB-per-tenant цей патерн **не транслюється напряму**. Цей розділ
систематизує чому і які є стратегії.

#### 3.8.2 Чому schema-варіант не переноситься на DB-варіант механічно

Принципова відмінність — у механізмі резолвінгу таблиці.

**Schema-per-tenant** використовує `search_path` PG. Один **logical**
SQL-запит `SELECT … FROM users_user` обирає фізично іншу таблицю
залежно від session-state connection'у (search_path). Маршрутизація
відбувається **в PG**, не в Django.

**DB-per-tenant** маршрутизує на рівні Django через `DATABASE_ROUTERS`.
Router отримує модель `User` і має повернути **один конкретний alias** —
`default` (master) або `tenant_<X>`. PG про tenant'ів нічого не знає;
кожна tenant-DB — окремий physical endpoint, окремий dbname, окремий
TCP-сокет, окремі credentials. Немає механізму «бери ту саму таблицю,
але з іншої БД на льоту» — DBs ізольовані за визначенням.

Тобто базовий router (як у §3.3.3) робить бінарне рішення:

```python
if model._meta.app_label in SHARED_APP_LABELS:
    return "default"
return f"tenant_{schema}" if schema else "default"
```

Він не вміє виразити «цей app має дві фізичні таблиці у двох місцях,
обирай за контекстом». А `allow_migrate` стандартного router'а
взаємовиключно мапить app на master ABO на tenants, але не на обидві.

Тому при наївному перенесенні `users` у обидва списки одна з гілок
ламається:

| Конфігурація | Що дає router | Що ламається |
|--------------|---------------|--------------|
| `users` у `SHARED_APP_LABELS` | Усі User-queries → master | Tenant DB не отримує `users_user`-таблицю (`allow_migrate` повертає False) → tenant-local users не існують → нікому логінитись на subdomain'ах |
| `users` НЕ у `SHARED_APP_LABELS` | User-queries → tenant DB (або master, якщо `current_tenant=None`) | Master не отримує `users_user`-таблицю → platform admin не існує → нікому логінитись на app.example.com |
| `users` фактично у обох списках Django | Django INSTALLED_APPS не має «двозначності»: app присутній або ні. Поведінка router'а визначає де він живе фізично | Залежить від router'а; стандартний router цей сценарій не підтримує |

Висновок: «app у обох списках» — це **семантика schema-per-tenant**, де
обидва місця матеріалізуються через search_path. У DB-per-tenant ту саму
семантику треба **явно сконструювати** одним з рішень нижче.

#### 3.8.3 Три стратегії

**Стратегія 1 (рекомендована): дві окремі моделі.**

Розділяємо логічну сутність «користувач» на дві фізичні моделі з різними
`app_label`:

```
platform_users/      ← у SHARED_APP_LABELS
    models.py:
        class PlatformUser(AbstractBaseUser):   # tenant_admin лише
            ...

tenant_users/        ← НЕ у SHARED_APP_LABELS
    models.py:
        class TenantUser(AbstractBaseUser):    # company_admin / driver / customer
            role = CharField(choices=...)
            ...
```

Router залишається бінарним (як §3.3.3). `PlatformUser.objects.get(...)`
іде на master, `TenantUser.objects.get(...)` — на current tenant.

**Переваги:**

- Чистий router без спецкейсів.
- PK-простори моделей **фізично ізольовані** — `PlatformUser.pk=1` і
  `TenantUser.pk=1` — це різні класи, не може бути плутанини.
- Можна мати різні поля у двох моделях (платформа і tenant'и часто
  справді мають різні потреби — у tenant_user є `driver_license_number`,
  у platform_user — `kpi_threshold` etc.).
- Auth-stack тривіальний: окремий backend + окремий endpoint видачі
  токенів. Жодних cross-context-конфузій можливо не може бути.

**Trade-off:** дві User-моделі замість однієї, два login-flow'и.

**Стратегія 2 (компроміс): одна модель + tri-state router.**

Якщо принципово потрібна **одна `User`-модель** (наприклад, є legacy-код,
що очікує саме `from django.contrib.auth import get_user_model`, або
auth-backend'и не легко роздвоюються), розширюємо router до три-станної
класифікації:

- `PUBLIC_ONLY_APPS` — живуть лише у master DB.
- `TENANT_ONLY_APPS` — живуть лише у tenant DBs.
- `SHARED_AND_TENANT_APPS` — фізично існують у master **і** у кожному
  tenant DB як окремі таблиці. Контекст вирішує куди йде запит.

**Реалізація router'а:**

```python
# tenants/routing/db_router.py
from tenants.routing.context import current_tenant


class TenantDBRouter:
    # Лише master.
    PUBLIC_ONLY_APPS = {"tenants", "admin", "sessions"}

    # Лише tenant DBs.
    TENANT_ONLY_APPS = {"orders", "cars", "drivers", "customers", "routes", "products"}

    # У ОБОХ — окрема фізична таблиця у master та у кожному tenant DB.
    # Контекст вирішує, куди йде запит:
    #   public host (current_tenant=None) → master
    #   tenant host (current_tenant="alpha") → tenant_alpha
    SHARED_AND_TENANT_APPS = {"auth", "contenttypes", "users"}

    def _route(self, model):
        label = model._meta.app_label
        if label in self.PUBLIC_ONLY_APPS:
            return "default"
        if label in self.TENANT_ONLY_APPS:
            schema = current_tenant.get()
            if not schema:
                # Запит до tenant-only моделі без контексту — це баг
                # (forgot to set current_tenant). Краще явний raise, ніж
                # тихий fallback на master.
                raise RuntimeError(
                    f"{model.__name__}: tenant-only model accessed without "
                    f"current_tenant set"
                )
            return f"tenant_{schema}"
        if label in self.SHARED_AND_TENANT_APPS:
            schema = current_tenant.get()
            return f"tenant_{schema}" if schema else "default"
        return None  # ← хай Django сам визначить (зазвичай default)

    def db_for_read(self, model, **hints):
        return self._route(model)

    def db_for_write(self, model, **hints):
        return self._route(model)

    def allow_relation(self, obj1, obj2, **hints):
        return obj1._state.db == obj2._state.db

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == "default":
            return (
                app_label in self.PUBLIC_ONLY_APPS
                or app_label in self.SHARED_AND_TENANT_APPS
            )
        # будь-який tenant_<X> alias
        return (
            app_label in self.TENANT_ONLY_APPS
            or app_label in self.SHARED_AND_TENANT_APPS
        )
```

Runtime-поведінка:

```
Запит на app.example.com (public host):
  middleware → current_tenant.set(None)
  view: User.objects.get(username="admin")
  router: app_label "users" ∈ SHARED_AND_TENANT_APPS, current_tenant=None
        → return "default"
  SELECT іде на master DB → знаходить platform-admin'а.

Запит на alpha.example.com (tenant host):
  middleware → current_tenant.set("alpha")
  view: User.objects.get(username="admin")
  router: app_label "users" ∈ SHARED_AND_TENANT_APPS, current_tenant="alpha"
        → return "tenant_alpha"
  SELECT іде на tenant_alpha DB → знаходить tenant-local company-admin'а.
```

`allow_migrate` гарантує, що `users` міграції накатуються і на master, і
на кожен tenant DB — обидві фізичні таблиці існують.

**Trade-off — архітектурні наслідки, які треба знати:**

1. **Cross-DB relations не існують у DB-per-tenant — це інваріант, не обмеження для обходу.** `allow_relation` тримає жорстку рівність `obj1._state.db == obj2._state.db` без винятків (§3.3.3), і будь-який Django-relation, що логічно перетнув би межу між master і tenant DB, у проекті не з'являється. Це **визначає форму FK-дизайну** у tenant-моделях:

   - **FK у межах одного tier'у — звичайний Django FK, без специфіки.** Tenant-модель може мати FK на іншу tenant-модель (Order → Driver), або на `User` у Strategy 2 (бо User фізично є у тій самій tenant DB через `SHARED_AND_TENANT_APPS`). У runtime'і обидві сторони такого relation'у читаються з одного й того ж tenant alias'а → `_state.db` збігаються → `allow_relation` пропускає природно. Жодного коду додавати не треба.

   - **FK на `PUBLIC_ONLY`-моделі (Tenant, Domain, тощо) із tenant-моделей — концептуально неможливі.** Constraint фізично не створиться (referenced-таблиця живе у іншій PG-database), `allow_relation` поверне False, ORM `select_related` між БД не вміє. Якщо логіка вимагає такого зв'язку — переформулювати без relation'а:

     - **Перевага 1: викинути поле взагалі.** Tenant-identity у DB-per-tenant **імпліцитна** — її несе сама БД, у якій лежить рядок. `Order.tenant_id`-поле у tenant_alpha-БД redundant: усі Order'и тут — alpha-ові за визначенням. Те ж саме для більшості «вказівників на public» у tenant-моделях.

     - **Перевага 2: loose pointer (без FK constraint'у).** Зберігати `<thing>_id` як звичайне `BigIntegerField`/`UUIDField` без relation. Resolve через два окремі запити: tenant-сторону через router (`current_tenant`-контекст), public-сторону явним `.using("default")`. Це — **не cross-DB query** (Django виконує два ізольовані запити), а просто application-level композиція даних.

   Обидві перевернутих стратегії **зберігають парадигму**: ORM ніколи не намагається з'єднати дані з двох БД у одному relation'і. Cross-DB-захист працює як інваріант на рівні router'а + `allow_relation` + DB-constraint'ів, і будь-який код, що писатиме під цей проект, фізично не може помилково створити cross-tenant leak через ORM-relation.

   *(Альтернатива «override `allow_relation` для специфічних пар» — не рекомендується. Вона дозволила б ORM-присвоєння `order.tenant = some_tenant`, але PG-constraint все одно не створюється і `select_related` не працює. Виходить semi-broken state, що дає оманливе враження working-relation'у — джерело тихих багів. Парадигма лишається без винятків.)*

2. **Auth-signal handlers і signal-handler'и моделей** (специфіка для DRF+JWT-stack'у). `django.contrib.auth.login()`/`logout()` у JWT-flow'і не викликаються, тому `user_logged_in`/`user_logged_out` **не шлються**. `user_login_failed` усе ж шлеться (simplejwt викликає `authenticate()` всередині `TokenObtainPairSerializer.validate()`), і його handler'и (audit, brute-force lockout, anomaly detection) спрацьовують і у tenant-, і у platform-контекстах. Те саме стосується custom `post_save`/`pre_save`-signals на `User`-моделі (якщо такі є) і token-blacklist-signals із `simplejwt.token_blacklist`. Будь-який такий handler має або:

   - Не залежати від `_state.db` об'єкта взагалі (працювати з тим alias'ом, який router йому дав).
   - АБО явно записувати result у `PUBLIC_ONLY`-модель (наприклад, централізований `AuthFailureLog` у master), щоб бути scope-agnostic.

   Тестувати у обох контекстах потрібно, але обсяг тестів значно менший, ніж у session-based проєктах — тільки `user_login_failed`-handler'и та model-signals на shared-моделях. Якщо у проекті custom handler'ів на User-signals немає і `user_login_failed` не обробляється — пункт можна вважати закритим.

3. **Cognitive load.** Дві фізичні `User`-таблиці у проєкті — більше
   сценаріїв для тестування, більше нюансів у operations. PK у двох
   таблицях не перетинаються логічно (бо різні contexts), але **фізично
   collide'ять** (бо це різні DB-послідовності). Це створює окремий
   security issue з JWT-авторизацією — детально у наступному
   аналітичному розділі **§3.9 «JWT identity confusion при одній User-моделі»**.

**Стратегія 3 (для специфічних кейсів): модель тільки на master + membership-таблиця.**

User завжди у master. Кожен `UserTenantMembership(user, tenant, role)`
описує, хто на якому tenant'і працює і з якою роллю. У tenant DB
користувачів не зберігаємо взагалі.

**Переваги:** найпростіший router (бінарний, users — суто public app),
єдина User-таблиця, тривіальна auth.

**Trade-off:** ламає логічну ізоляцію «tenant видалив свого user'а».
Видалення user'а робить tenant deletion централізованою операцією, що
торкається master'а. Compliance може цього не приймати, якщо BAA
вимагає, щоб tenant сам володів даними своїх users. Для типового SaaS
із вимогою «tenant видалив driver'а — рядок щез з усіх систем» — не
підходить.

#### 3.8.4 Decision matrix

| Критерій | Стратегія 1 (дві моделі) | Стратегія 2 (tri-state) | Стратегія 3 (master-only + membership) |
|----------|-------------------------|-------------------------|----------------------------------------|
| Складність router'а | Бінарний | Tri-state, явні exception'и | Бінарний |
| PK-collisions у JWT | Неможливо | **Можливо, потребує окремого захисту** (див. §3.9) | Неможливо |
| FK з tenant-моделі на User | Природні (FK на TenantUser у тій самій tenant DB) | Природні (User у `SHARED_AND_TENANT`, тенант DB має свою копію) | Не застосовно (User тільки на master, прямого FK з tenant-моделі немає; через `UserTenantMembership`-loose-pointer) |
| Auth-stack | Два backend'и, два endpoint'и | Один backend, але треба JWT scope-check | Один backend |
| Кейс tenant-local users (driver/customer) | ✅ Природно | ✅ З урахуванням наслідків | ❌ Концептуально проблемно |
| Compliance: tenant володіє своїми users | ✅ | ✅ | ⚠️ Залежить від політики |
| Cognitive load | Низький | Високий | Середній |

**Дефолтна рекомендація — Стратегія 1.** Вона зміщує ціну з runtime-нюансів
у дизайн-час (треба раз продумати дві моделі) і дає найменшу operational
surface area. Стратегія 2 — компроміс для legacy-проєктів чи коли
absolutely потрібен єдиний UserManager / get_user_model() для всіх
контекстів. Стратегія 3 — нішева, для специфічних compliance-models.

#### 3.8.5 Зв'язок із розділом про JWT

Стратегія 2 створює один особливий security-issue, який не покривається
самим router'ом: PK у master і у tenant DBs формально різні, але JWT
ідентифікує користувача через PK і нічого не каже про DB-scope.
Аналітика і фікси — у наступному розділі §3.9 «JWT identity confusion
при одній User-моделі, спільній для master і tenant DB». Для Стратегій 1
і 3 ця проблема не виникає за визначенням.

---

### 3.9 JWT identity confusion при одній User-моделі, спільній для master і tenant DB

#### 3.9.1 Коли цей розділ актуальний

Тільки якщо обрано **Стратегію 2** з §3.8 — одна `User`-модель, що
живе фізично у master DB і у кожному tenant DB одночасно як **окремі
таблиці**. У Стратегіях 1 і 3 проблема не виникає (моделі/таблиці
структурно різні або єдині).

#### 3.9.2 Анатомія проблеми

Три факти, що разом створюють вразливість:

1. **JWT ідентифікує користувача через `user_id` (PK)**, без посилання на
   БД. У `djangorestframework-simplejwt` за дефолтом payload = `{user_id,
   exp, iat, jti, token_type}` без жодного DB-scope claim'у.

2. **PK у master і у кожному tenant DB перетинаються**, бо це окремі
   sequence-простори. `pk=1` існує одночасно у `master.users_user`
   (platform admin), у `tenant_alpha.users_user` (driver Petrenko), у
   `tenant_beta.users_user` (customer Ivanenko) — це **три різні фізичні
   рядки, три різні людини**.

3. **Tenant визначається з Host header'у запиту**, а не з токена.
   `TenantDBMiddleware` читає subdomain → `current_tenant.set("alpha")`
   → router відправляє наступний `User.objects.get(pk=1)` у `tenant_alpha`.

З цих трьох фактів випливає: JWT, виданий у одному контексті, авторизує
зовсім іншого користувача у запиті до іншого host'у — і всі захисні
перевірки (signature, expiry, user existence) проходять штатно.

#### 3.9.3 Сценарії експлуатації

**Сценарій A: tenant → platform (privilege escalation).**

```
1. Driver Petrenko логіниться на alpha.example.com.
2. simplejwt видає access-token:
       payload = {user_id: 1, exp: ..., ...}
       signature = HMAC-SHA256(payload, SECRET_KEY)

3. Токен потрапляє до зловмисника (XSS, leaked logs, MITM при misconfigured
   TLS, malicious browser extension, або сам Petrenko випадково копіпастить
   його у curl).

4. Зловмисник шле запит, НЕ модифікуючи токен:
       GET app.example.com/api/tenants/
       Authorization: Bearer <same-token>

5. Сервер:
   а) TenantDBMiddleware: Host = "app.example.com" не tenant-host
      → current_tenant.set(None).
   б) simplejwt JWTAuthentication:
      - signature valid (SECRET_KEY ОДИН для всього сервера) ✅
      - exp valid ✅
      - User.objects.get(id=1) → router → master DB
      - SELECT * FROM master.users_user WHERE id=1
      - повертає PLATFORM ADMIN (user_id=1 у master).
   в) request.user = platform_admin, request виконується з його правами.

6. Зловмисник з token'ом driver'а отримав права platform admin'а.
```

**Сценарій B: platform → tenant (impersonation).** Дзеркальний:
токен platform_admin'а (`pk=1` у master) на host'і tenant'а авторизує
як tenant_alpha-user'а з `pk=1` (driver Petrenko). Менш катастрофічно
ніж A, але дає identity-confusion у audit-логах і доступ до
tenant-local endpoint'ів від чужого імені.

#### 3.9.4 Чому signature не закриває це

Поширений рефлекс: «JWT же підписаний, значить безпечно».

Підпис захищає від **модифікації payload'у**. Якщо атакуючий спробує:

```python
payload = decode(token)
payload["tenant"] = "public"        # ← хоче переключити контекст
new_token = base64(header) + "." + base64(payload) + "." + OLD_SIGNATURE

# Сервер:
expected_sig = HMAC_SHA256(new_header + "." + new_payload, SECRET_KEY)
if expected_sig != old_signature:
    raise InvalidSignature           # ← 401, forge провалений
```

— signature ламається на перший байт зміни. Без `SECRET_KEY` атакуючий
**не може** перепідписати модифікований payload.

Але у сценаріях A і B **payload не модифікується**. Підпис залишається
валідним, бо токен справді наш. Реверсивно: signature гарантує «ми
підписали цей токен», вона **нічого не каже про те, у якому контексті
цей токен має використовуватись**.

Тобто vulnerability не у тому, що атакуючий **підробив** токен — у тому,
що валідний токен **переноситься між Host-контекстами**, і сервер цю
невідповідність не помічає.

#### 3.9.5 Захист 1 (рекомендований): tenant-claim у JWT + перевірка scope-match

Додаємо `tenant` як обов'язковий claim у payload при видачі токена.
Перевіряємо його у custom authentication class:

```python
# tenants/jwt_auth.py
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from tenants.routing.context import current_tenant


class TenantScopedJWTAuthentication(JWTAuthentication):
    """JWTAuthentication, що валідує `tenant`-claim у токені проти
    поточного tenant-контексту запиту.

    Закриває cross-tenant identity confusion: валідний токен, виданий для
    tenant X, не приймається у запиті до host'а tenant Y. Підпис гарантує
    «токен наш»; цей check гарантує «токен — для цього request-scope».
    """

    def get_validated_token(self, raw_token):
        validated_token = super().get_validated_token(raw_token)

        request_tenant = current_tenant.get() or "public"
        token_tenant = validated_token.get("tenant")

        if token_tenant is None:
            # Старі токени без claim'у або forge-спроби із зрізаним
            # payload'ом. Жорстко відкидаємо — поточна політика вимагає
            # tenant scope у кожному токені.
            raise InvalidToken("Token missing 'tenant' claim")

        if token_tenant != request_tenant:
            raise InvalidToken(
                f"Token tenant scope='{token_tenant}' does not match "
                f"request tenant='{request_tenant}'"
            )

        return validated_token
```

Як інжектити `tenant` у токен при видачі:

```python
# tenants/jwt_serializers.py
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from tenants.routing.context import current_tenant


class TenantScopedTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # `current_tenant` встановлений TenantDBMiddleware'ом перед тим,
        # як цей view виконується — тобто tenant scope береться з Host'у,
        # на якому користувач логіниться. Це і фіксується у токені.
        token["tenant"] = current_tenant.get() or "public"
        return token
```

Settings'ом підмінюємо стандартні DRF/simplejwt класи:

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tenants.jwt_auth.TenantScopedJWTAuthentication",
    ],
}

SIMPLE_JWT = {
    "TOKEN_OBTAIN_SERIALIZER": (
        "tenants.jwt_serializers.TenantScopedTokenObtainPairSerializer"
    ),
}
```

Поведінка після впровадження:

| Сценарій | До захисту | Після захисту |
|----------|-----------|---------------|
| Driver Petrenko (alpha) → alpha.example.com | ✅ як Petrenko | ✅ як Petrenko |
| Driver Petrenko (alpha) → app.example.com (Сценарій A) | ❌ як platform_admin | ✅ 401 InvalidToken |
| Platform admin → app.example.com | ✅ як platform_admin | ✅ як platform_admin |
| Platform admin → alpha.example.com (Сценарій B) | ❌ як random tenant user | ✅ 401 InvalidToken |
| Token без `tenant`-claim'у (старі / forged) | (не існували) | ✅ 401 InvalidToken |

**Переваги:**

- Один if в auth backend'і; решта проекту не змінюється.
- `tenant`-claim — частина підписаного payload'у → tamper-evident.
- Працює із refresh-токенами (claim успадковується при refresh, бо
  `TokenObtainPairSerializer.get_token` використовується і для access,
  і для refresh).

**Caveats:**

- Refresh-flow: переконатись, що `TokenRefreshSerializer` теж зберігає
  `tenant` (за дефолтом simplejwt це робить — refresh видає новий access
  з тим самим payload'ом, мінус `token_type` і `exp`).
- Стратегія міграції: якщо у проді вже є виданні токени без `tenant` —
  тимчасово допустити їх (логуючи warning), потім перейти на жорсткий
  rejection після того, як старі токени expire'нуться.

#### 3.9.6 Захист 2 (альтернатива): per-tenant signing keys

Замість одного `SECRET_KEY` на сервер — окремий ключ per tenant
(включно з `public`):

```python
# settings.py
TENANT_JWT_KEYS = {
    "public": env("JWT_KEY_PUBLIC"),    # окремі секрети у Secrets Manager
    "alpha":  env("JWT_KEY_ALPHA"),
    "beta":   env("JWT_KEY_BETA"),
    ...
}
```

У `JWTAuthentication.get_validated_token` обираємо ключ за поточним
`current_tenant.get()`. Токен, підписаний alpha-ключем, на public host
не пройде signature verification → 401 на криптографічному рівні,
без application-level check'а.

**Переваги:**

- Крипто-гарантія, а не application-level if. Якщо хтось забуде про
  check у новому endpoint'і — атака все одно не пройде (signature
  invalidate'иться).
- Compromise одного tenant'ового ключа не зачіпає інших — корисно для
  blast-radius reduction.

**Caveats:**

- Складніший key management: при створенні tenant'а треба генерувати
  ключ, при видаленні — invalidate'ити (всі активні токени
  деактивуються одразу — feature, не bug, але треба знати).
- Refresh-token rotation складніша.
- Якщо плануєш cross-tenant tokens у майбутньому (наприклад, SSO між
  pre-vetted tenant'ами) — додатковий layer.

#### 3.9.7 Decision matrix між захистами

| Сценарій | Захист 1: `tenant`-claim | Захист 2: per-tenant keys |
|----------|--------------------------|---------------------------|
| Простота впровадження | Низька (новий клас + claim) | Середня (key management) |
| Зміни у бізнес-коді | Нульові | Нульові |
| Захист від forge | ✅ через signature | ✅ через signature |
| Захист від cross-host replay | ✅ через if | ✅ криптографічно |
| Blast-radius compromise'у SECRET'а | Усі tenant'и | Тільки компрометований |
| Складність моніторингу та rotation | Просто | Помірно |

**Дефолтна рекомендація**: **Захист 1** (`tenant`-claim). Реалізується
двома невеликими файлами (custom JWT auth + custom serializer) і
закриває весь клас вразливості. Захист 2 — overkill для більшості
проектів, обирається якщо у threat-model'і є вимога мінімізації
blast-radius при compromise'і.

#### 3.9.8 Що змінюється у бізнес-коді

Нічого. Це — фікс інфраструктурного шару (auth backend + token issuer).
Views, viewsets, serializers, Celery tasks — лишаються незмінними.
Захист працює на рівні DRF authentication, до того як view взагалі
викликається.

---

## Реалізація тестового проєкта на django-tenants + DB schemas

Усе попереднє (§0-§3) — аналітика, теорія, рекомендації. Нижче — фактична
реалізація цього демо-проекту: довідник із розгортання, експлуатації та
розширення. Архітектурний вибір тут — **schema-per-tenant** (стандартний
django-tenants), бо це достатньо для демо. Реальні prod-міркування щодо
DB-per-tenant — у §3 вище.

### 1. Requirements

- Python 3.10+
- PostgreSQL 13+ (django-tenants потребує підтримки схем — SQLite не підійде)
- venv `p_env` із чекаута, або свіжий

```bash
source ../p_env/bin/activate           # або: python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Database

Multi-tenant потребує PostgreSQL (django-tenants не працює з SQLite). У
розділі два сценарії: швидкий для локального дева (§2.1) і повний для
прод-розгортання на RDS/Aurora з перевіркою доступів (§2.2-§2.10).

#### 2.1 Швидкий локальний dev

Для розробки на своїй машині достатньо одного superuser-юзера і одної
БД:

```sql
CREATE USER postgres WITH SUPERUSER PASSWORD 'postgres';
CREATE DATABASE tenants_back OWNER postgres;
```

Креденшіали можна перевизначити env-змінними (`DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST`, `DB_PORT`) — за замовчуванням
`postgres / postgres @ 127.0.0.1:5432`. Для дева перевірка доступів,
окрема роль і власник схеми не потрібні — superuser може все.

#### 2.2 Передумови (production)

Далі — повний цикл для прод-розгортання: від чистого RDS/Aurora-кластера
до робочої БД, в яку Django зможе мігрувати схеми. Алгоритм підходить і
для self-hosted PostgreSQL — відрізняються лише деталі підключення
в §2.3.

- AWS Aurora PostgreSQL (або звичайний PostgreSQL 13+) уже піднятий.
- У тебе є endpoint, master-user (наприклад, `ubuntu`) і його пароль.
- На сервері застосунку встановлений `psql`:
  ```bash
  sudo apt install -y postgresql-client
  ```
- (Для Aurora) Security Group дозволяє inbound 5432 з IP сервера застосунку:
  ```bash
  nc -zv <rds-endpoint> 5432            # має відповісти "succeeded"
  ```

#### 2.3 Підключитись як master

```bash
PGPASSWORD='<master-pass>' psql -h <rds-endpoint> -U ubuntu -d postgres
```

> Альтернатива з інтерактивним вводом — без `PGPASSWORD`-префікса; не лишає
> пароль у `~/.bash_history`.

#### 2.4 Створити роль і БД

```sql
-- 1. Окрема роль для застосунку (НЕ master).
CREATE ROLE tenants_back WITH LOGIN PASSWORD '<секрет>';

-- 2. Дати master-юзеру тимчасове членство в новій ролі.
--    Без цього CREATE DATABASE з OWNER іншої ролі падає в Aurora з
--    помилкою «must be member of role».
GRANT tenants_back TO ubuntu;

-- 3. Сама БД.
CREATE DATABASE tenants_back OWNER tenants_back ENCODING 'UTF8';

-- 4. Прибрати тимчасове членство (опційно, для гігієни).
REVOKE tenants_back FROM ubuntu;
```

#### 2.5 Передати `public` схему у власність застосунку

Aurora створює нову БД зі схемою `public`, власник якої — master. У PG 14
це поки не блокує `tenants_back` від створення там таблиць, але **у PG 15+
тільки власник схеми може створювати в ній об'єкти**. Передаємо власність
наперед — щоб майбутній upgrade Aurora нічого не зламав:

```bash
PGPASSWORD='<master-pass>' psql -h <rds-endpoint> -U ubuntu -d tenants_back
```

```sql
ALTER SCHEMA public OWNER TO tenants_back;
\dn
--   Name  |    Owner
-- --------+---------------
--  public | tenants_back     ← має стати так
\q
```

#### 2.6 (Опційно) Увімкнути PostGIS

Тільки якщо проект використовує гео-поля (`PointField`, `LineStringField`).
Виконувати **як master** — `CREATE EXTENSION` потребує `rds_superuser`:

```bash
PGPASSWORD='<master-pass>' psql -h <rds-endpoint> -U ubuntu -d tenants_back
```

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT PostGIS_Version();          -- очікуєш 3.x
GRANT USAGE ON SCHEMA public TO tenants_back;          -- якщо ще не передавали власність
GRANT SELECT ON ALL TABLES IN SCHEMA public TO tenants_back;
\q
```

Повна налагодка PostGIS у Django (`ORIGINAL_BACKEND`, `django.contrib.gis`,
гео-поля, міграції) — окремо в §15.

#### 2.7 Перевірити, що `tenants_back` має всі потрібні доступи

Підключись **уже як новий юзер**:

```bash
PGPASSWORD='<секрет>' psql -h <rds-endpoint> -U tenants_back -d tenants_back
```

Чек-лист команд:

```sql
-- 1) Ідентичність і поточна БД
SELECT current_user, current_database();

-- 2) Атрибути ролі (login, createdb, superuser, ...)
\du tenants_back

-- 3) Поточні схеми і їх власники
\dn

-- 4) Чи можемо створити СХЕМУ — потрібно для auto_create_schema нових тенантів
CREATE SCHEMA __perm_test;
DROP SCHEMA __perm_test;

-- 5) Чи можемо створити ТАБЛИЦЮ у public — туди йдуть SHARED_APPS міграції
CREATE TABLE public.__perm_test (id int);
INSERT INTO public.__perm_test VALUES (1);
SELECT count(*) FROM public.__perm_test;     -- → 1
DROP TABLE public.__perm_test;

-- 6) Чи доступні PostGIS-типи (тільки якщо робили §2.6)
SELECT 'POINT(30.5 50.4)'::geometry;

-- 7) Привілеї на public (точніший погляд)
SELECT has_schema_privilege(current_user, 'public', 'CREATE')  AS can_create,
       has_schema_privilege(current_user, 'public', 'USAGE')   AS can_use;

-- 8) Привілеї на БД (CONNECT, CREATE на рівні БД)
SELECT has_database_privilege(current_user, current_database(), 'CONNECT') AS can_connect,
       has_database_privilege(current_user, current_database(), 'CREATE')  AS can_create_schemas,
       has_database_privilege(current_user, current_database(), 'TEMP')    AS can_temp;

\q
```

Що має повернути `TRUE`:

| Перевірка                                       | Чому це важливо                                                    |
|--------------------------------------------------|--------------------------------------------------------------------|
| `current_user = tenants_back`                    | Підключились правильно                                             |
| `has_database_privilege ... 'CONNECT'`           | Інакше Django не зможе відкрити з'єднання                          |
| `has_database_privilege ... 'CREATE'`            | Потрібно для `CREATE SCHEMA <new_tenant>` при `auto_create_schema` |
| `has_schema_privilege public 'CREATE'`           | Потрібно для SHARED_APPS-міграцій (`auth_user`, `tenants_*`, ...) |
| `has_schema_privilege public 'USAGE'`            | Доступ до PostGIS-функцій і базових Django-таблиць у public        |
| `CREATE SCHEMA __perm_test` працює               | Те саме що `CREATE` на БД, але перевірено практично                |
| `CREATE TABLE public.__perm_test` працює         | Те саме що `CREATE` на public, перевірено практично                |
| (Якщо PostGIS) `'POINT(...)'::geometry` працює   | PostGIS-extension встановлений і доступний                          |

#### 2.8 Якщо щось не пускає

| Симптом у §2.7                                       | Що зробити                                                                                                                       |
|------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| `permission denied for schema public` у п. 5         | Не передавали власність схеми. Зайти master'ом: `ALTER SCHEMA public OWNER TO tenants_back;` або `GRANT ALL ON SCHEMA public TO tenants_back;` |
| `permission denied for database tenants_back` у п. 4 | `tenants_back` не власник БД. Зайти master'ом: `ALTER DATABASE tenants_back OWNER TO tenants_back;`                              |
| `type "geometry" does not exist`                     | Extension не створений. Зайти master'ом: `CREATE EXTENSION postgis;` (§2.6)                                                      |
| `FATAL: password authentication failed`              | Невірний пароль АБО роль не має `LOGIN`. Master'ом: `ALTER ROLE tenants_back WITH LOGIN PASSWORD '...';`                          |
| `could not connect ... timeout`                      | RDS Security Group не пускає з твоєї IP. AWS Console → RDS → твій кластер → Security groups → Inbound → додати 5432 з твого CIDR. |

#### 2.9 Записати креди в `settings_local.py`

Після успішної перевірки скопіювати плейсхолдери `settings_local.py.example`
у `settings_local.py` (gitignored) і заповнити реальні значення:

```python
DATABASES["default"].update({
    "NAME": "tenants_back",
    "USER": "tenants_back",
    "PASSWORD": "<секрет>",
    "HOST": "<rds-endpoint>",
    "PORT": "5432",
})
```

> **Важливо**: `ENGINE` в `update()` НЕ перевизначаємо — він уже виставлений
> у `settings.py` як `django_tenants.postgresql_backend`. Для PostGIS-режиму
> досить `ORIGINAL_BACKEND` (теж у `settings.py`, див. §15).

#### 2.10 Перший запуск міграцій

```bash
cd /home/ubuntu/tenants_back
source .env/bin/activate
python manage.py migrate_schemas --shared          # SHARED_APPS у public
python manage.py bootstrap_public ...              # tenant_admin
python manage.py bootstrap_tenant --schema alpha ... # перший тенант
```

Якщо тут падає на `migrate_schemas --shared` із `permission denied`,
повертайся до §2.7 і знайди, яка з 8 перевірок дала `f` (false).

---

### 3. Hosts file (тільки для дев)

Multi-tenancy керується hostname'ом. У `/etc/hosts`:

```
127.0.0.1   localhost alpha.localhost beta.localhost gamma.localhost
```

### 4. Локальні налаштування — `settings_local.py`

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

### 5. First-time setup

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

### 6. Hostname → URL conf mapping

| Host                | URL conf                              | Призначення              |
|---------------------|---------------------------------------|--------------------------|
| `localhost`         | `tenants_back.urls_public`            | Керування тенантами      |
| `alpha.localhost`   | `tenants_back.urls_tenant`            | Бізнес-API alpha         |
| `beta.localhost`    | `tenants_back.urls_tenant`            | Бізнес-API beta          |
| `gamma.localhost`   | `tenants_back.urls_tenant`            | Бізнес-API gamma         |

`TenantMainMiddleware` перемикає PostgreSQL `search_path` за hostname'ом
ще до того, як хоч один view торкнеться БД.

---

### 7. Roles

| Роль             | Де живе       | Де логіниться             | Що може                                |
|------------------|---------------|---------------------------|----------------------------------------|
| `tenant_admin`   | `public`      | `localhost`               | CRUD тенантів; Django admin на public  |
| `company_admin`  | tenant schema | `<tenant>.localhost`      | Повний CRUD сутностей + Django admin   |
| `customer`       | tenant schema | `<tenant>.localhost`      | Каталог + замовлення                   |
| `driver`         | tenant schema | `<tenant>.localhost`      | Призначені маршрути (read-only)        |

У кожній схемі — своя таблиця `auth_user`, тож унікальність username'у —
лише в межах одного тенанта (`admin` у alpha й `admin` у beta — різні акаунти).

---

### 8. Як працює ізоляція юзерів між схемами

Чому `tenant_admin` фізично неможливо залогінити на `alpha.localhost`, і
навпаки — `admin@alpha` на `localhost`? Це не магія в коді — це наслідок
того, як `django-tenants` мапить моделі на PostgreSQL schemas плюс як
Postgres резолвить `search_path`.

#### 8.1 Один app у двох списках → дві фізичні таблиці

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

#### 8.2 Як `search_path` маршрутизує SQL

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

#### 8.3 Куди фізично потрапляють користувачі

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

#### 8.4 Що відбувається при спробі залогінитись «не туди»

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

#### 8.5 Перевірити «руками»

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

#### 8.6 Підводні камені, на які цей патерн НЕ страхує

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

### 9. Міграції в django-tenants — мінігайд

#### 9.1 Що важливо розуміти спочатку

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

#### 9.2 Команди — шпаргалка

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

#### 9.3 Розгортання з нуля

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

#### 9.4 Внесення змін у існуючий проект

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

#### 9.5 Чи може структура **однієї таблиці** відрізнятись?

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

#### 9.6 Підводні камені

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

#### 9.7 Робочий чекліст для деплою змін

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

### 10. Створення нового тенанта в існуючій системі

`bootstrap_tenant` зручний для першого розгортання, але в живому проді
тенанти зазвичай додаються одним із трьох шляхів. У всіх трьох є
*спільний підводний камінь*: створення `Tenant` + `Domain` ще НЕ створює
користувачів усередині нової схеми. Перший `company_admin` потрібно
доробити окремо — інакше `https://delta.example.com/admin/` пустить нікого.

#### 10.1 Через Django admin на public-сайті

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

#### 10.2 Через REST API

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

#### 10.3 Через ORM у `manage.py shell`

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

#### 10.4 Як добити перший `company_admin` після створення (§10.1 / §10.2)

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

#### 10.5 Як видалити тенант

`Tenant.auto_drop_schema = True` (вже виставлено у моделі) робить так,
що `Tenant.delete()` фізично дропає схему з усіма таблицями. Через
admin: вибрати тенант → Delete. Або:

```python
Tenant.objects.get(schema_name="delta").delete()   # → DROP SCHEMA delta CASCADE
```

⚠️ Це **незворотньо** — даних після цього не повернеш окрім як з бекапа БД.

---

### 11. API surface

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

### 12. Валідації (вбудовано в моделі/серіалайзери)

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

### 13. Quick smoke test (curl)

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

### 14. Production deployment

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

### 15. (Опційно) Підтримка PostGIS

Якщо проекту потрібні геометричні типи (`Point`, `LineString`, `Polygon`),
spatial-індекси і GIS-запити у БД (`distance_lte`, `within`, ...) — нижче
покроковий алгоритм. Якщо досить просто зберігати координати + рахувати
дистанції в Python — пропусти цей розділ і використай
`DecimalField(lat) + DecimalField(lng)`.

#### 15.1 Системні залежності на сервері

```bash
sudo apt update
sudo apt install -y binutils libproj-dev gdal-bin libgdal-dev libgeos-dev libgeos++-dev
```

#### 15.2 Увімкнути PostGIS у БД

Підключись як master (`ubuntu` має `rds_superuser`, потрібний для
`CREATE EXTENSION`):

```bash
PGPASSWORD='<master-pass>' psql -h <rds-endpoint> -U ubuntu -d tenants_back
```

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT PostGIS_Version();        -- перевірка: має повернути версію 3.x

-- Якщо public ще не належить tenants_back — хоча б видай grant:
GRANT USAGE ON SCHEMA public TO tenants_back;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO tenants_back;
\q
```

#### 15.3 Налаштувати Django через `ORIGINAL_BACKEND`

`django-tenants` має офіційну settings-змінну, яка переключає базовий
backend із звичайного PostgreSQL на PostGIS. **Кастомний backend із
multiple inheritance не потрібен.**

У `tenants_back/settings.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",   # ← лишається той самий
        # NAME / USER / PASSWORD / HOST / PORT — без змін
    }
}

# Нова стрічка: говорить django-tenants успадковуватись від PostGIS-backend
# замість стандартного PostgreSQL.
ORIGINAL_BACKEND = "django.contrib.gis.db.backends.postgis"

# Додай django.contrib.gis у SHARED_APPS:
SHARED_APPS = [
    "django_tenants",
    "tenants",

    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.gis",          # ← новий рядок
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",

    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",

    "users",
]
# TENANT_APPS не чіпаємо.
```

#### 15.4 Додати гео-поля у моделі

Імпорти GIS-полів — окремі, з `django.contrib.gis.db.models`:

```python
# routes/models.py
from django.contrib.gis.db import models as gis_models
from django.db import models


class Route(models.Model):
    name = models.CharField(max_length=120)
    # ... існуючі поля ...

    start_point = gis_models.PointField(geography=True, null=True, blank=True)
    path = gis_models.LineStringField(geography=True, null=True, blank=True)
```

#### 15.5 Згенерувати міграції

```bash
source .env/bin/activate
python manage.py makemigrations routes
```

Відкрий згенерований файл. Якщо у списку `operations` побачиш:

```python
migrations.CreateExtension('postgis'),
```

**прибери цей рядок**. У Aurora роль `tenants_back` не має
`rds_superuser` → виконання впаде з `permission denied`. Extension ми
вже створили руками master-юзером у кроці 15.2.

#### 15.6 Накотити міграції

```bash
python manage.py migrate_schemas
```

#### 15.7 Зібрати статику адмінки

```bash
python manage.py collectstatic --noinput
sudo supervisorctl restart tenants_back
```

GeoDjango додає OpenLayers-віджет у Django admin для гео-полів — його
CSS/JS потрапить у `staticfiles/` через `collectstatic`.

#### 15.8 Перевірити в БД

```bash
PGPASSWORD='<секрет>' psql -h <rds-endpoint> -U tenants_back -d tenants_back
```

```sql
\dx                            -- має бути postgis у списку
SET search_path TO alpha, public;
SELECT 'POINT(30.5 50.4)'::geometry;   -- тип резолвиться з public

\d alpha.routes_route          -- гео-колонки серед полів
\di alpha.routes_route_*       -- GiST-індекси (Django GIS їх створює автоматично)
```

#### 15.9 Тонкі моменти

| #  | Гачок                                                          | Деталь                                                                                                                                  |
|----|-----------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| 1  | **`ORIGINAL_BACKEND` ≠ `ENGINE`**                               | `ENGINE` лишається `django_tenants.postgresql_backend`. Якщо змінити саме `ENGINE` на postgis-варіант — мульти-тенантність зламається.   |
| 2  | **PostGIS extension живе тільки в `public`**                    | Не треба `CREATE EXTENSION postgis` у кожній тенантній схемі. Тип `geometry` резолвиться через search_path → `<тенант>, public` → знаходить у public. |
| 3  | **`django.contrib.gis` — у SHARED_APPS, не в TENANT_APPS**      | Це бібліотека з полями + GIS ORM, без власних DB-моделей. У TENANT_APPS додавати нема сенсу.                                            |
| 4  | **`CreateExtension` у міграції Django**                         | Django може автоматично додати `migrations.CreateExtension('postgis')` у файл після першої `makemigrations`. Aurora-роль `tenants_back` цього не виконає. Видаляєш рядок з міграції — extension вже на місці з кроку 15.2. |
| 5  | **Extra-схеми від PostGIS (`tiger`, `topology`, `tiger_data`)** | Якщо ставив повний набір (`postgis_topology`, `postgis_tiger_geocoder`), вони існуватимуть у БД як окремі схеми. Власник — `rdsadmin`. Це нормально; вони видимі тенантам через search_path, але django-tenants ними не керує. |
| 6  | **`geography=True` vs `geography=False`**                       | `True` — координати на сфері WGS84, точні відстані глобально, повільніше. `False` (= `geometry`) — площинні, швидше, але дистанції викривлені поза малими регіонами. Для логістики в одній країні `geography=True` природніше. |
| 7  | **DRF не серіалізує геометрію з коробки**                       | Стандартний `ModelSerializer` падає на `PointField`. Якщо плануєш віддавати гео-поля через API — серіалізуй вручну (`point.x`, `point.y` як два DecimalField-и) або візьми окремий пакет з GIS-серіалайзерами. |
| 8  | **OpenLayers-віджет у адмінці на гео-полях**                    | Django admin за замовчуванням рендерить великий інтерактивний мапа-віджет на `PointField`. Якщо це не треба — у `ModelAdmin` перевизнач `formfield_overrides` на простий `TextField`-widget. |
| 9  | **Rollback гео-поля втратить дані**                             | Зворотній `RemoveField` для `PointField` дропає колонку. Якщо колись треба буде відкатити — спершу зроби data-migration, що зберігає `ST_AsText(field)` у звичайну текстову колонку. |
| 10 | **`auto_create_schema=True` клонує `template1`**                | Нова тенантна схема НЕ дістає extensions автоматично — і це нормально, бо ми тримаємо postgis тільки в public. Якщо колись захочеш кожному тенанту окремий postgis — постав extension у `template1` ДО створення першого тенанта. |
| 11 | **Upgrade Aurora major version може зачепити PostGIS**          | При переході PG 14 → 15 Aurora не оновлює PostGIS автоматично. Перед major upgrade зроби `SELECT postgis_extensions_upgrade();` у БД. Краще описано в AWS docs «Upgrading PostGIS». |

#### 15.10 Швидкий чеклист

- [ ] `apt install -y binutils libproj-dev gdal-bin libgdal-dev libgeos-dev libgeos++-dev`
- [ ] `CREATE EXTENSION postgis` виконано як master, `PostGIS_Version()` повертає версію
- [ ] У `settings.py` додано `ORIGINAL_BACKEND = "django.contrib.gis.db.backends.postgis"`
- [ ] `django.contrib.gis` додано у `SHARED_APPS`
- [ ] `ENGINE` лишився `django_tenants.postgresql_backend` (НЕ змінювали)
- [ ] Гео-поля додано в моделі
- [ ] `CreateExtension('postgis')` прибрано зі згенерованої міграції
- [ ] `migrate_schemas` пройшов чисто
- [ ] `\d <schema>.<table>` показує гео-колонки + GIST-індекс
- [ ] `collectstatic` зібрав OpenLayers-ассети

---

### 16. Project layout

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
