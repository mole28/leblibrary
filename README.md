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
LebLibrary is a Django-based web application serving as a centralized repository for Torah articles, halachic books, and responsa (Q&A). Alongside its reading interface and book catalog, the platform integrates custom computational search tools, a multi-dialect Aramaic-Hebrew lexicon, and AI-assisted research modules. It also features a hybrid "AI-Suggests, Editor-Decides" knowledge graph that connects articles, book chapters, responsa, and research tools into curated topical learning paths.

---

## ✨ Key Features
- **Article & Book Management:** Structured reading interface for articles and multi-chapter books with a built-in reading progress indicator and digital bookstore, alongside a distraction-free Zen reading mode, Dark Mode support, and inline admin publishing controls.
- **Editorial Knowledge Graph & Topic Clusters ("AI-Suggests, Editor-Decides"):** Curated continuation panels and thematic topic hubs (*Brachot*, *Shabbat & Moadim*, *Eretz Yisrael*, *Family & Brit Milah*, *Taharah & Shiurim*, and *Choshen Mishpat*) managed via a dedicated Editorial Audit Dashboard (`/connections-audit/`) and live inline article controls, allowing the editor to approve, reject, or manually bind bidirectional links between articles, book chapters, Q&A responsa, and custom research tools.
- **Multi-Corpus Torah Search Engine:** Fast text and computational search across Tanakh, Mishnah, Tosefta, Babylonian Talmud, Jerusalem Talmud, Rambam, and Shulchan Aruch. Supports exact/broad matching, full/defective Hebrew spelling with prefix matching (*Ktiv Maleh/Chaser*), Gematria calculations, acronyms (*Rashei/Sofei Tevot*), word reversals, and intra-word/cross-word verse Equidistant Letter Sequences (ELS). Powered by high-speed SQL bigram pre-filtering, C-level nikkud stripping, and shareable URLs that persist custom multi-corpus selections and active search filters.
- **Aramaic ⇄ Hebrew Lexicon & Translator:** Bidirectional dictionary and morphological analyzer partitioned into Babylonian Talmud, Jerusalem Talmud, and Zohar dialects, featuring root/affix breakdown and live corpus citations.
- **Halachic Measurement Calculators:** Interactive conversion tools for biblical and talmudic units of length, volume, and weight/coins.
- **Talmudic Acronyms Dictionary:** Live-search database for decoding rabbinic and halachic abbreviations, featuring automatic in-text hover tooltips (`lux-acronym`) that decode abbreviations directly within articles and book chapters.
- **SEO & Structured Data:** Integrated with Google Search Console, Schema.org (`JSON-LD`), IndexNow, and `llms.txt` for search and AI indexing, alongside comprehensive dynamic XML sitemaps (articles, books, Q&A, and static tools), strict canonical URL enforcement, and automated legacy 301 redirects.

---

## 🤖 AI-Powered Capabilities & Agents
The platform integrates specialized AI modules and data-analysis workflows:
1. **Content & Knowledge Expert Agent:** Performs hybrid semantic and keyword search across the library's repository to provide grounded answers with direct source citations. Augmented with Editorially Curated RAG (`ClusterEngine`), automatically injecting editor-approved related articles, book chapters, and responsa into the AI context.
2. **Site Navigation & Orientation Agent:** Assists users in exploring the platform by routing queries to relevant tools, calculators, and articles.
3. **AI Audio Generation (Text-to-Speech):** Automated Hebrew neural voice narration (`Edge-TTS`) with a custom rabbinic abbreviation pronunciation dictionary.
4. **Corpus Data Analysis & Concept Mapping:** Cross-references terms across all Torah corpora, Gematria equivalents, and ELS patterns to generate interactive network graphs (`Vis.js`) and structured topical syntheses.

---

## 🛠️ Tech Stack
- **Backend:** Python, Django, PostgreSQL / SQLite, Custom Editorial Knowledge Graph (`ClusterEngine`)
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
