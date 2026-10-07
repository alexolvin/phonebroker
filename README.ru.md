# PhoneBroker

**Языки:** [English](README.md) | Русский

<p align="left">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg">
</p>

Брокер-сервис ADB для одного телефона. Обеспечивает эксклюзивный доступ к
одному Android-телефону для клиентских проектов через lease/queue API
с токенами на проект, лимитами на площадку и белым списком ADB-операций.

## Возможности

- **Эксклюзивные аренды (lease)** — одна активная аренда за раз; остальные
  запросы встают в очередь с приоритетом (`interactive` | `background`)
  и защитой от голодания.
- **Берер-токены на проект** — у каждого клиентского проекта свой токен
  (`PHONEBROKER_TOKEN_*`); токен владельца отклоняется на проектных эндпоинтах.
- **Лимиты на площадку** — минимальный интервал между арендами и дневной
  лимит, настраиваются по площадкам и приоритетам.
- **Только белый список ADB-операций** — сырого `adb shell` через API нет:
  launch, tap, tap_selector, swipe, text, keyevent, screenshot, ui_dump, wait_for.
- **Режим обслуживания (maintenance)** — владелец приостанавливает весь
  клиентский трафик (`/maintenance/*`) и работает с телефоном напрямую.
- **Защищённая интеграция с хостом** — отдельный системный пользователь
  `phonebroker`, nftables-правила, ограничивающие ADB-порты этим пользователем,
  SSH-демон с forced command на порту 2222 для владельца, systemd-юниты, udev.
- **Синхронизация пакетов площадок** — `make platforms` сопоставляет
  установленные пакеты телефона с площадками по ключевым словам
  и поддерживает привязку в актуальном состоянии.

## Требования

- Linux-хост (проверено на Debian/Ubuntu) с `systemd`, `nftables`, `openssh-server`
- Python 3.12+
- ADB (`adb` в PATH) и один Android-телефон, подключённый по USB с включённым ADB
- `sudo` для установки
- Опционально: Tailscale на хосте — установщик привязывает приватный sshd
  к Tailscale IP, если он доступен; иначе sshd слушает `0.0.0.0`
- Опционально (удобство владельца): Windows-ноутбук с PowerShell 5.1+,
  `scrcpy` и `adb` для доступа к экрану

## Быстрый старт

```bash
git clone https://github.com/alexolvin/phonebroker.git
cd phonebroker

# 1. Укажите ADB serial телефона (adb devices) в config/broker.yaml:
#    adb:
#      serial: "YOUR_ADB_SERIAL"

# 2. Установка (системный пользователь, udev, nftables, systemd, ADB-ключ,
#    токены, ADBKeyBoard):
sudo make install
# Лог: /tmp/phonebroker-install.log

# 3. На ноутбуке (PowerShell) — SSH config + phone.ps1 + проверка:
#    установщик выведёт точные команды scp + powershell

# 4. Установите приложения площадок на телефон, затем привяжите пакеты:
sudo make platforms
# Лог: /tmp/phonebroker-platforms.log

# 5. Прогоните приёмочные тесты T1–T12:
sudo make acceptance
# Лог: /tmp/phonebroker-acceptance.log
```

Сервис слушает `127.0.0.1:8090`.

## Конфигурация

В репозитории — `config/broker.yaml` со значениями по умолчанию;
`make install` копирует его в `/etc/phonebroker/broker.yaml`,
который является единственным runtime-источником.

| Ключ | Назначение | По умолчанию |
|---|---|---|
| `port` | Порт API | `8090` |
| `adb.serial` | ADB serial телефона — **заполнить обязательно** | `YOUR_ADB_SERIAL` |
| `heartbeat_timeout_s` | Аренда возвращается в очередь, если клиент перестал слать heartbeat | `60` |
| `check_interval_s` | Интервал перепроверки очереди | `2` |
| `starvation_threshold` | Очередная аренда поднимается после N проверок | `5` |
| `platforms.<id>.package` | Пакет, привязанный к площадке | `""` |
| `platforms.<id>.keywords` | Ключевые слова для автоматического сопоставления | `[]` |
| `platforms.<id>.limits` | Переопределение лимитов площадки | `{}` |
| `defaults.background` / `defaults.interactive` | `min_interval_s`, `max_daily_leases` | см. файл |
| `clients.<name>` | Запись на каждый клиентский проект; для каждого генерируется токен | — |
| `data_dir` | SQLite + скриншоты | `/var/lib/phonebroker` |

**Токены.** `make install` генерирует `PHONEBROKER_TOKEN_OWNER` и по одному
`PHONEBROKER_TOKEN_<NAME>` на клиента в `/etc/phonebroker/env`
(root:phonebroker, 640). Ротация одного токена:

```bash
sudo make token PROJECT=client_a
```

## Использование

Все проектные эндпоинты требуют `Authorization: Bearer <токен>`.

```bash
# Запросить аренду (201 active, 202 waiting)
curl -X POST http://127.0.0.1:8090/lease \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"platform":"vinted","operation":"listing","priority":"background","max_duration_s":600}'

# Продлить аренду
curl -X POST http://127.0.0.1:8090/lease/<id>/heartbeat -H "Authorization: Bearer $TOKEN"

# Выполнить операцию из белого списка
curl -X POST http://127.0.0.1:8090/lease/<id>/ops/launch -H "Authorization: Bearer $TOKEN"

# Завершить аренду
curl -X DELETE http://127.0.0.1:8090/lease/<id> -H "Authorization: Bearer $TOKEN"
```

**Эндпоинты (18):**

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Состояние сервиса и телефона |
| POST | `/lease` | Запрос аренды (201/202) |
| GET | `/lease/{id}` | Статус аренды |
| DELETE | `/lease/{id}` | Завершить активную аренду |
| POST | `/lease/{id}/heartbeat` | Heartbeat |
| GET | `/leases` | Аренды проекта |
| GET | `/lease/{id}/history` | Журнал операций |
| POST | `/maintenance/start` | Начать обслуживание (владелец) |
| POST | `/maintenance/renew` | Продлить обслуживание (владелец) |
| POST | `/maintenance/end` | Завершить обслуживание (владелец) |
| POST | `/lease/{id}/ops/launch` | Запустить пакет площадки |
| POST | `/lease/{id}/ops/tap` | Тап в `x`,`y` |
| POST | `/lease/{id}/ops/tap_selector` | Тап по UI-селектору |
| POST | `/lease/{id}/ops/swipe` | Свайп `x1,y1 → x2,y2` |
| POST | `/lease/{id}/ops/text` | Ввод текста (Unicode) |
| POST | `/lease/{id}/ops/keyevent` | Отправка keyevent |
| POST | `/lease/{id}/ops/screenshot` | Скриншот (base64) |
| POST | `/lease/{id}/ops/ui_dump` | Dump UI-иерархии |
| POST | `/lease/{id}/ops/wait_for` | Ожидание селектора |

**Управление:**

```bash
sudo make token PROJECT=client_a   # ротация токена
sudo make platform ID=olx_pl PACKAGE=pl.tablica   # привязка пакета
sudo make platform ID=olx_pl PACKAGE=-            # отвязка
sudo make uninstall                # полный откат
```

## Структура проекта

```text
config/           значения по умолчанию broker.yaml, sshd_config, карта токенов
scripts/          install/uninstall, привязка площадок, проверки, pre-commit hook
src/phonebroker/  FastAPI-приложение: api/, lease, queue, adb, maintenance, packages
systemd/          phonebroker, phonebroker-adb, phonebroker-sshd, phonebroker-nft
tests/            юнит-тесты + приёмочная серия T1–T12
tools/windows/    настройка ноутбука владельца (PowerShell)
```

## Тестирование

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

make test        # юнит-тесты
make gates       # проверки hardcode / secrets / powershell / adb-usage + shellcheck
make acceptance  # T1–T12 против установленной системы (нужен телефон)
```

## Безопасность

В репозитории нет секретов; токены хранятся в `/etc/phonebroker/env`
(root:phonebroker, 640) и резолвятся во время выполнения.
ADB-порты (5037, 27183) ограничены nftables пользователем `phonebroker`.
Сообщать об уязвимостях — через [SECURITY.md](SECURITY.md).

## Участие

См. [CONTRIBUTING.md](CONTRIBUTING.md).

## Лицензия

Проект распространяется по лицензии MIT. Текст лицензии: [LICENSE](LICENSE).
