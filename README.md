# 📈 Dexcom Glucose Logger (G4/G5/G6/G7)

A self-hosted, mobile-friendly dashboard that logs Dexcom (G4/G5/G6/G7) glucose readings to a local database.

![Python](https://img.shields.io/badge/Python-3.14-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![GitHub pkgs](https://img.shields.io/badge/Container-GHCR-blue?logo=github)

> **Why this exists:** The official Dexcom Share API limits data retrieval to the last 24 hours. This application bypasses that limitation by automatically syncing readings to a local SQLite database, giving you ownership of your long-term health history.

---

## ✨ Features

### 📊 Glucose Tracking
* **Long-Term History:** Automatically saves every reading to a local `glucose.db` file, bypassing the 24-hour API limit.
* **Smart Sync:** Intelligent background syncing that fills in data gaps instantly without crashing your server.
* **Visual Trends:** Interactive charts showing glucose history (24h to 90 Days) and "Time in Range" statistics.
* **Printer Friendly:** One-click "Print" mode formatted perfectly for doctor visits.

### 🍽️ Meal Analysis
* **Log Meals:** Fast, mobile-friendly interface to log food, carbs, and notes.
* **Carb Calculator:** **(New)** Built-in search tool powered by the USDA database. Enter items (e.g., "1 apple, 2 eggs") to automatically calculate total carbs.
* **Spike Detection:** Automatically calculates glucose "Rise" (Peak - Start) for every meal.
* **Carb Analysis:** "Carbs vs. Glucose Rise" scatter plot to identify which foods cause the biggest spikes.
* **Full Management:** Edit or delete past meals to fix mistakes.
  
### 💾 Data Freedom
* **Health Export:** One-click CSV export of glucose readings formatted for medical analysis tools (Glooko/Tidepool).
* **Meal Export:** Download your full meal history as a CSV for your own records.
* **Local Privacy:** All data lives on *your* server. Nothing is sent to third parties.

---

## 🖼️ Screenshots

<p align="center">
  <img src="screenshots/logs.jpeg" width="45%" alt="Glucose Log View" />
  <img src="screenshots/trends.jpeg" width="45%" alt="Trends View" />
</p>

_Left: The main log providing a clean, sortable history. Right: The new trends dashboard with Time-in-Range visualization._

---

## ✅ Prerequisites

Before running this logger, ensure:
1.  **Dexcom Share is Enabled:** The main Dexcom account **must** have the "Share" feature enabled in the mobile app.
2.  **At Least One Follower:** Dexcom often requires at least one active follower (or pending invitation) for the Share API to function.

---

## 🚀 Quick Start

The easiest way to run this is with Docker Compose. You do not need to clone the repository code, you only need the configuration file.

1.  **Create a folder** for the project:
    ```bash
    mkdir dexcom-logger
    cd dexcom-logger
    ```

2.  **Create a `compose.yaml` file:**
    Create a file named `compose.yaml` and paste the following:

    ```yaml
    services:
      web:
        image: ghcr.io/nuken/dexcom-glucose-logger:latest
        container_name: dexcom-web
        restart: unless-stopped
        ports:
          - 5000:5000
        environment:
          - DEXCOM_USER=your_username_here
          - DEXCOM_PASS=your_password_here
          - DEXCOM_OUS=False # Set to True if outside US
          - USDA_API_KEY=your_key_here # Optional: Get free key at fdc.nal.usda.gov
          - TZ=America/New_York
          - PYTHONUNBUFFERED=1
        volumes:
          - glucose_data:/app/data

    volumes:
      glucose_data:
    ```

3.  **Run it:**
    ```bash
    docker compose up -d
    ```

4.  **Access the Dashboard:**
    Open your browser and go to `http://your-server-ip:5000`

---

## 🖥️ Portainer / Dockge

If you use a dashboard like Portainer or Dockge, you can deploy this as a **Stack**.

**Stack Configuration:**

 ```yaml
    services:
      web:
        image: ghcr.io/nuken/dexcom-glucose-logger:latest
        container_name: dexcom-web
        restart: unless-stopped
        ports:
          - 5000:5000
        environment:
          - DEXCOM_USER=your_username_here
          - DEXCOM_PASS=your_password_here
          - DEXCOM_OUS=False # Set to True if outside US
          - USDA_API_KEY=your_key_here # Optional: Get free key at fdc.nal.usda.gov
          - TZ=America/New_York
          - PYTHONUNBUFFERED=1
        volumes:
          - glucose_data:/app/data

    volumes:
      glucose_data:
    ```

---

## 🍎 Carb Calculation Setup (Beta)

The "Calculate Carbs" button uses the **USDA FoodData Central API** to search for nutrition info.

1.  **Get a Free API Key:**
    * Go to **[https://fdc.nal.usda.gov/api-key-signup](https://fdc.nal.usda.gov/api-key-signup.html)**.
    * Fill out the form to receive your key instantly via email.

2.  **Add to Config:**
    * Add the key to your `compose.yaml` file:
        ```yaml
        environment:
          - USDA_API_KEY=your_long_api_key_here
        ```
    * Restart your container: `docker compose up -d`.

> **Note:** If you do not provide a key, the app will use the public `DEMO_KEY`, which is limited to **50 searches per day**.

---

## ⚙️ Configuration

You can configure the application using environment variables in `compose.yaml`:

| Variable | Description | Default |
| --- | --- | --- |
| `DEXCOM_USER` | **Required.** Your Dexcom account username. | `None` |
| `DEXCOM_PASS` | **Required.** Your Dexcom account password. | `None` |
| `DEXCOM_OUS` | Set to `True` if you live outside the US (International Account). | `False` |
| `USDA_API_KEY`| **Optional.** Key for carb lookups. | `DEMO_KEY` |
| `TZ` | Sets the timezone for the logs (e.g., `America/New_York`). | `UTC` |

---

## 🛠️ Troubleshooting

**The time is wrong/UTC:**
Ensure you have set the `TZ` environment variable in your `compose.yaml` to your local timezone (e.g., `America/Chicago`).

**I don't see data older than 24 hours:**
When you first install the logger, it can only "see" what Dexcom allows (the last 24 hours). As you leave the container running, it will build up your history day by day. In a week, you will have 7 days of data!

**"Background Sync Failed" in logs:**
This usually happens if the password is incorrect or Dexcom servers are temporarily down. The logger will automatically retry in 30 minutes.

---

## 🔒 Privacy & Data

This application stores your personal health data in a local volume named `glucose_data` on your server.

* **Ownership:** You own this data. It never leaves your server.
* **Backup:** We recommend backing up the volume regularly.
* **Security:** Ensure your server is secure and not exposed to the public internet without proper authentication (like a VPN or Authelia).

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/nuken/dexcom-glucose-logger/issues).

## Acknowledgements

* **[pydexcom](https://github.com/gagebenne/pydexcom):** This project relies on the excellent library by [Gage Benne](https://github.com/gagebenne) to communicate with the Dexcom Share API.

## 📄 License

This project is [MIT](https://www.google.com/search?q=LICENSE) licensed.





