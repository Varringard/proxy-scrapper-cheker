# ⚡ ProxyPulse — Прокси Скрапер, Чекер и Ротационный Шлюз

Современный, легковесный веб-сервис для автоматического сбора (scraping), многопоточной валидации (checking) прокси-серверов любых протоколов (**HTTP**, **HTTPS**, **SOCKS4**, **SOCKS5**), с определением задержки (ping), геолокации и уровня анонимности (**Elite**, **Anonymous**, **Transparent**), а также встроенным **ротационным шлюзом** и красивым темным веб-интерфейсом.

Поднимается **одной командой** через Docker Compose без конфликтов портов и сложных зависимостей.

---

## 🌟 Ключевые возможности

- 🚀 **Запуск в 1 команду**: Полностью автономный стек, разворачивающийся за 5 секунд через `docker compose up -d`.
- 🌐 **40+ встроенных источников сбора**: Автоматический парсинг сотен тысяч публичных прокси из актуальных репозиториев и фидов (TheSpeedX, Monosans, ShiftyTR, ProxyScrape API, Hookzof, Jetkai и др.).
- ⚡ **Высокоскоростной асинхронный чекер**: До 100-500 одновременных потоков на `asyncio` и `aiohttp-socks`. Проверяет пинг с миллисекундной точностью, доступность и тип анонимности.
- 🔄 **Встроенный локальный ротационный шлюз (порт 8081)**:
  - Вы можете указать `http://localhost:8081` в любом софте, браузере, парсере или curl.
  - Шлюз сам выбирает лучший живой прокси из пула (стратегии: `fastest` — самый быстрый, `round-robin` — по очереди, `random` — случайный).
  - Поддерживает HTTPS tunneling (`CONNECT`).
  - При сбое прокси мгновенно переключается на следующий рабочий узел.
- 🗺️ **Определение геопозиции (GeoIP)**: Страна, код флага (🇺🇸, 🇩🇪, 🇷🇺) и город без ограничений по внешним API благодаря встроенному пакетному кэшированию.
- 🎨 **Современный Cyberpunk/Glassmorphism Web UI**:
  - Живой WebSocket-терминал событий и логов в реальном времени.
  - Панели распределения протоколов, типов анонимности и топа стран.
  - Удобная таблица с поиском, фильтрами, сортировкой и возможностью одиночного экспресс-теста любого узла.
- 📥 **Импорт и Экспорт**:
  - Быстрый импорт: вставьте список в любом текстовом формате — регулярные выражения автоматически найдут IP и порты.
  - Экспорт в **TXT** (`ip:port` или `proto://ip:port`), **JSON**, **CSV**, **PAC** и **ProxyChains**.
  - Прямые ссылки на API для использования в других скриптах и ботах.

---

## 🚀 Быстрый запуск

### 1. Запуск через Docker Compose (Рекомендуется)

```bash
# Клонируйте репозиторий или перейдите в папку проекта:
cd proxy-scrapper-cheker

# Запустите контейнер:
docker compose up -d
```

После этого откройте в браузере:
👉 **Панель управления**: [http://localhost:8080](http://localhost:8080)  
👉 **Ротационный прокси-шлюз**: `http://localhost:8081`

---

## ⚙️ Переменные окружения (.env)

Вы можете изменить настройки в файле `.env` (или скопировать из `.env.example`):

| Переменная | По умолчанию | Описание |
|---|:---:|---|
| `WEB_PORT` | `8080` | Порт веб-интерфейса и REST API |
| `GATEWAY_PORT` | `8081` | Порт встроенного ротационного шлюза |
| `GATEWAY_ENABLED` | `true` | Включить/выключить ротационный шлюз |
| `GATEWAY_STRATEGY` | `fastest` | Стратегия шлюза: `fastest`, `random`, `round-robin` |
| `CHECKER_CONCURRENCY` | `100` | Число одновременных асинхронных проверок |
| `CHECKER_TIMEOUT` | `6.0` | Таймаут проверки прокси (в секундах) |
| `CHECK_TARGET_URL` | `http://httpbin.org/ip` | URL для тестирования коннекта и анонимности |
| `AUTO_SCRAPE_INTERVAL` | `0` | Интервал авто-сбора в секундах (`0` = выключен, `3600` = каждый час) |
| `AUTO_CHECK_INTERVAL` | `0` | Интервал авто-проверки в секундах (`0` = выключен, `1800` = каждые 30 мин) |

---

## 💡 Примеры использования ротационного шлюза (порт 8081)

Подключите любую программу к `http://localhost:8081`:

### cURL:
```bash
curl -x http://localhost:8081 https://api.ipify.org?format=json
```

### Python (Requests):
```python
import requests

proxies = {
    "http": "http://localhost:8081",
    "https": "http://localhost:8081"
}

response = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)
print("Outgoing IP:", response.json())
```

### Python (httpx):
```python
import httpx

with httpx.Client(proxy="http://localhost:8081") as client:
    resp = client.get("https://api.ipify.org?format=json")
    print(resp.json())
```

### Node.js (Axios):
```javascript
import axios from 'axios';
import { HttpsProxyAgent } from 'https-proxy-agent';

const agent = new HttpsProxyAgent('http://localhost:8081');
const { data } = await axios.get('https://api.ipify.org?format=json', { httpsAgent: agent });
console.log(data);
```

---

## 📡 REST API & Интеграции

Платформа предоставляет готовые эндпоинты для автоматизации:

- `GET /api/stats` — полная статистика в JSON (число живых/мертвых, средний пинг, протоколы).
- `GET /api/proxies` — список прокси с пагинацией и фильтрами (`?alive=1&protocol=socks5&max_latency=1000`).
- `GET /api/export` — прямая ссылка на выгрузку:
  - `GET /api/export?format=txt&alive=1` (список `IP:PORT`)
  - `GET /api/export?format=txt&alive=1&with_protocol=true` (`protocol://IP:PORT`)
  - `GET /api/export?format=json&alive=1`
  - `GET /api/export?format=proxychains` (для файла `proxychains.conf`)
- `POST /api/scraper/start` — запуск сбора прокси.
- `POST /api/checker/start` — запуск проверки пула.
- `POST /api/proxies/import` — ручной импорт прокси пачкой.
- `DELETE /api/proxies/dead` — мгновенная очистка недоступных узлов.
- `WS /api/ws` — WebSocket для отслеживания прогресса в реальном времени.

---

## 🛠️ Архитектура

```
┌────────────────────────────────────────────────────────┐
│                      ProxyPulse                        │
├──────────────────────────┬─────────────────────────────┤
│   Web Dashboard & API    │   Rotating Proxy Gateway    │
│       (:8080)            │          (:8081)            │
│  FastAPI + WebSocket     │  Asyncio HTTP/CONNECT Tunnel│
├──────────────────────────┴─────────────────────────────┤
│                    Core Engines                        │
│  ┌───────────────────────┐   ┌──────────────────────┐  │
│  │    Scraper Manager    │   │   Checker Manager    │  │
│  │ 40+ Sources + Regex   │   │ aiohttp-socks Pool   │  │
│  └───────────────────────┘   └──────────────────────┘  │
│                          │                             │
│                  SQLite DB (WAL Mode)                  │
│               Persistent in ./data volume              │
└────────────────────────────────────────────────────────┘
```

---

## 📄 Лицензия

MIT License. Свободно для личного и коммерческого использования.
