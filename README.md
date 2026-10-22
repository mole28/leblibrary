# LebLibrary
### ספריית לייבוביץ

A digital library, research platform, and article management system built to provide accessible Torah scholarship, halachic literature, and computational text-analysis tools.

**Live Site:** [https://leblibrary.co.il](https://leblibrary.co.il)

---

## 📸 Preview
> *Screenshot of the live platform interface.*
![LebLibrary Preview](docs/screenshot.png)

---

## 📖 Overview
LebLibrary is a Django-based web application serving as a centralized repository for Torah articles, halachic books, and responsa (Q&A). Alongside its reading interface and book catalog, the platform integrates custom computational search tools, a multi-dialect Aramaic-Hebrew lexicon, and AI-assisted research modules.

---

## ✨ Key Features
- **Article & Book Management:** Structured reading interface for articles and multi-chapter books with a built-in reading progress indicator and digital bookstore.
- **Multi-Corpus Torah Search Engine:** Fast text and computational search across Tanakh, Mishnah, Tosefta, Babylonian Talmud, Jerusalem Talmud, Rambam, and Shulchan Aruch. Supports exact/broad matching, Gematria calculations, acronyms (*Rashei/Sofei Tevot*), word reversals, and Equidistant Letter Sequences (ELS).
- **Aramaic ⇄ Hebrew Lexicon & Translator:** Bidirectional dictionary and morphological analyzer partitioned into Babylonian Talmud, Jerusalem Talmud, and Zohar dialects, featuring root/affix breakdown and live corpus citations.
- **Halachic Measurement Calculators:** Interactive conversion tools for biblical and talmudic units of length, volume, and weight/coins.
- **Talmudic Acronyms Dictionary:** Live-search database for decoding rabbinic and halachic abbreviations.
- **SEO & Structured Data:** Integrated with Google Search Console, Schema.org (`JSON-LD`), IndexNow, and `llms.txt` for search and AI indexing.

---

## 🤖 AI-Powered Capabilities & Agents
The platform integrates specialized AI modules and data-analysis workflows:
1. **Content & Knowledge Expert Agent:** Performs hybrid semantic and keyword search across the library's repository to provide grounded answers with direct source citations.
2. **Site Navigation & Orientation Agent:** Assists users in exploring the platform by routing queries to relevant tools, calculators, and articles.
3. **AI Audio Generation (Text-to-Speech):** Automated Hebrew neural voice narration (`Edge-TTS`) with a custom rabbinic abbreviation pronunciation dictionary.
4. **Corpus Data Analysis & Concept Mapping:** Cross-references terms across all Torah corpora, Gematria equivalents, and ELS patterns to generate interactive network graphs (`Vis.js`) and structured topical syntheses.

---

## 🛠️ Tech Stack
- **Backend:** Python, Django, PostgreSQL
- **Frontend:** HTML5, CSS3, Bootstrap 5, JavaScript, Vis.js
- **AI & Audio:** Google Gemini API, ChromaDB (Vector Search), Microsoft Edge-TTS
- **Server & Monitoring:** Ubuntu Linux, Gunicorn, Nginx, Sentry
- **Version Control:** Git & GitHub

---

## 🚀 Getting Started (Local Development)
To run this project locally for development or testing:

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/mole28/leblibrary.git](https://github.com/mole28/leblibrary.git)
   cd leblibrary

2. **Install dependencies:**
    ```bash
    pip install -r requirements.txt

3. **Run database migrations:**
    ```bash
    python manage.py migrate

4. **Start the development server:**
    ```bash
    python manage.py runserver

---

## 📋 Deployment & Maintenance Cheat Sheet
This section documents the standard workflow for updating the live production server.

### 1. Pushing Local Changes (Development Environment)
After modifying templates (e.g., `base.html`), adding static files, or updating Python logic:

    # Stage all changes
    git add .

    # Commit with a descriptive message
    git commit -m "Update description here"

    # Push to the main branch
    git push