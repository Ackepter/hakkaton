# Smart Intersection — Система управления умным перекрёстком

Веб-система для моделирования, мониторинга и управления дорожным перекрёстком с поддержкой AUTO/MANUAL/FAILSAFE режимов, симуляции трафика и (в будущем) компьютерного зрения и GPIO Raspberry Pi.

---

## Содержание

- [Требования](#требования)
- [Быстрый старт](#быстрый-старт)
- [Запуск на Windows / WSL Debian 12](#запуск-на-windows--wsl-debian-12)
- [Запуск на Raspberry Pi](#запуск-на-raspberry-pi)
- [Конструктор города](#конструктор-города)
- [Камеры и компьютерное зрение](#камеры-и-компьютерное-зрение)
- [Режимы работы](#режимы-работы)
- [Архитектура](#архитектура)
- [API](#api)

---

## Требования

| Компонент | Версия |
|-----------|--------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |

---

## Быстрый старт

### 1. Backend

```bash
cd hakkaton

# Создать виртуальное окружение
python3 -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / WSL / macOS
source .venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Скопировать конфигурацию
cp .env.example .env

# Запустить backend
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Backend будет доступен на: http://localhost:8000

Swagger UI: http://localhost:8000/docs

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend будет доступен на: http://localhost:5173

---

## Запуск на Windows / WSL Debian 12

```bash
# WSL Debian 12
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm

git clone <repo> hakkaton
cd hakkaton

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Terminal 1 — Backend
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
```

---

## Запуск на Raspberry Pi

### Системные зависимости

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm
# Для камеры:
sudo apt install -y libcamera-dev v4l-utils
# Для GPIO (если нужен физический светофор):
sudo apt install -y python3-rpi.gpio
```

### Запуск

```bash
cd hakkaton
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# В .env задать:
# HARDWARE_MODE=raspberry
# CAMERA_MODE=usb
# RUN_MODE=raspberry
# VIDEO_SOURCE=0

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Доступ к интерфейсу с компьютера: `http://<raspberry-ip>:8000`

---

## Запуск без оборудования (Simulation Mode)

```bash
# .env (или по умолчанию)
HARDWARE_MODE=mock
CAMERA_MODE=simulation
RUN_MODE=simulation

python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

В simulation mode генерируются виртуальные автомобили, грузовики и пешеходы. Камера и GPIO не нужны.

---

## Тесты

```bash
# Убедитесь что .venv активирован
pytest tests/ -v

# Конкретный модуль
pytest tests/test_controller.py -v
pytest tests/test_simulation.py -v
pytest tests/test_api.py -v

# Камеры и компьютерное зрение
pytest tests/test_vision_*.py -v
pytest tests/test_e2e_vision.py -v        # запускает SI и backend отдельными процессами

# Smart Intersection
pytest smart_intersection/tests -v

# Конструктор (последний тест управляет настоящим Chrome; нужны свободные порты 8000/8001/5173)
pytest tests/test_frontend_geometry.py tests/test_vision_sync.py tests/test_e2e_builder.py -v
```

Тесты **не требуют** Raspberry Pi или реального оборудования.

---

## Конструктор города

Конструктор встроен прямо в 3D-симуляцию: кнопка **🏗 Build mode** на странице «3D Simulation». Как в градостроительном
симуляторе, можно ставить и двигать здания, деревья, фонари, остановки и камеры, включать и укорачивать дороги, делать
автобусные полосы и трамвайные пути, добавлять пешеходные переходы, задавать поток машин и людей, а логику светофора
собирать из блоков (фаза, лампы, длительность) или оставить адаптивной. Города сохраняются и загружаются, есть готовые
раскладки. Во время симуляции транспорт и пешеходов можно добавлять кликом рядом с дорогой.
Подробности и формат JSON: [docs/constructor.md](docs/constructor.md).

---

## Камеры и компьютерное зрение

Камера подключается через `config/cameras.yaml`: `simulation` (виртуальная камера над Smart Intersection),
`usb`, `file` (видеофайл вместо камеры в WSL), `network`. Детекция — `virtual` (данные симуляции) или локальный
`yolo` (CPU, без CUDA, `pip install -r requirements-yolo.txt`). На Dashboard слева видеопоток с рамками
распознанных объектов, справа состояние перекрёстка; в 3D-сцене камера показана как объект, а панель справа
транслирует её картинку. Потеря камеры, отказ YOLO или недоступность симуляции переводят светофоры в FAILSAFE,
интерфейс продолжает работать. **Камера не обязательна** для запуска.

Подробности, API, зоны и настройка: [docs/cameras-and-vision.md](docs/cameras-and-vision.md).

---

## Режимы работы

### AUTO
Система автоматически переключает фазы светофоров на основе загруженности полос. Алгоритм учитывает количество автомобилей, грузовиков и пешеходов в очередях.

### MANUAL
Пользователь вручную управляет каждым светофором через Dashboard. Ручное управление имеет высший приоритет над логикой AUTO.

### FAILSAFE
Активируется автоматически при:
- потере видеопотока с камеры
- сбое модуля YOLO
- потере соединения

В FAILSAFE режиме светофоры работают по заранее заданным фиксированным таймингам (RED 20с → YELLOW 3с → GREEN 15с → YELLOW 3с).

---

## Архитектура

```
Common code
    │
    ├── TrafficController (AUTO/MANUAL/FAILSAFE)
    │       └── TrafficLight (phases, timing)
    │
    ├── SimulationEngine (virtual traffic)
    │
    ├── MetricsCollector (statistics)
    │
    ├── HardwareInterface
    │       ├── MockGPIO (dev/WSL)
    │       └── RaspberryPiGPIO (production)
    │
    └── Vision (backend/vision, независим от контроллера и GPIO)
            ├── CameraSource: SimulationSource / UsbSource / FileSource / NetworkSource
            ├── Detector: VirtualDetector / YoloDetector
            └── TrafficAnalyzer → Dashboard, FAILSAFE, Smart Intersection
```

### Платформозависимый код

| Компонент | WSL / Windows | Raspberry Pi |
|-----------|--------------|--------------|
| GPIO | `MockGPIO` | `RaspberryPiGPIO` |
| Camera | Simulation / Video file | USB Camera |
| YOLO | Virtual detection или YOLO на CPU | YOLOv8n на CPU (`imgsz: 320`) или вынос на другой ПК |

---

## API

Полная документация: http://localhost:8000/docs

### Основные endpoints

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/intersection` | Получить конфигурацию перекрёстка |
| POST | `/api/intersection` | Сохранить конфигурацию |
| GET | `/api/lights` | Состояния всех светофоров |
| POST | `/api/lights/manual` | Ручное управление светофором |
| POST | `/api/control/mode` | Переключить режим AUTO/MANUAL/FAILSAFE |
| POST | `/api/control/simulation` | Управление симуляцией |
| GET | `/api/metrics` | Текущие метрики |
| GET | `/api/metrics/history` | История метрик |
| WS | `/ws` | WebSocket для real-time обновлений |

### WebSocket

Подключение: `ws://localhost:8000/ws`

Сервер отправляет каждые 500мс:
```json
{
  "type": "state_update",
  "ts": 1234567890.0,
  "mode": "AUTO",
  "lights": [...],
  "metrics": {...},
  "simulation_running": true
}
```

---

## Структура проекта

```
hakkaton/
├── backend/
│   ├── api/             REST endpoints
│   ├── config/          Настройки
│   ├── hardware/        GPIO абстракция (Mock + RaspberryPi)
│   ├── metrics/         Сбор метрик
│   ├── models/          Pydantic schemas
│   ├── simulation/      Симулятор трафика
│   ├── traffic/         Контроллер светофоров
│   ├── core.py          Глобальный state
│   └── main.py          FastAPI приложение
├── frontend/
│   └── src/
│       ├── pages/       Constructor, Dashboard
│       ├── components/  UI компоненты
│       ├── hooks/       useWebSocket
│       └── api/         HTTP клиент
├── config/              config.yaml
├── tests/               pytest тесты
├── requirements.txt
└── .env.example
```

---

## Совместимость Raspberry Pi

Перед переносом на Raspberry Pi убедитесь:
- [ ] Тесты проходят в WSL
- [ ] Simulation mode работает без камеры
- [ ] Mock GPIO заменяет физический
- [ ] `.env` настроен для Pi (`HARDWARE_MODE=raspberry`, `CAMERA_MODE=usb`)
- [ ] GPIO pins заданы в конфигурации, не зашиты в код

Обратите внимание: PyTorch / YOLOv8 на Raspberry Pi 3B+ работают медленно (~1–2 FPS). Для демонстрации рекомендуется запускать YOLO на ПК и передавать результаты детекции на Pi по сети (архитектурно уже предусмотрено через абстракцию).
