# Northbridge Bank: Data Mapping Agent (Tool 3)

An AI agent that finds which database column holds a bank business term
(for example "Interest-only mortgage" -> `mortgage_loans.repayment_type = 'IO'`).

- **Groq** is the mapper (the agent loop). **Gemini** is the independent checker.
- **Only a human data owner approves** an answer. The AI has no approve job.
- Runs in **Google Colab**, with the data in Google Drive.
- **Synthetic data only.** No real bank data, systems or code.

## Files

| File | What it is |
|---|---|
| `northbridge_colab_app.py` | The whole app as one Colab cell (jobs 0-6, agent loop, checker, 3-tab screen, evaluation, usage stats) |
| `northbridge_colab_app_code.pdf` | The same code as a PDF |
| `Data mapping agen solution design architecture.html` | Design document (architecture, guardrails, tests, results, learnings) |
| `load_data.py` | Builds the synthetic database and data dictionary (step 0) |
| `data/northbridge_uk_loans.db` | Synthetic UK loans database: 20 tables |
| `data/data_dictionary.csv` | Column descriptions, with gaps planted on purpose |
| `data/eval/` | Answer key and planted flaws, used **only** for marking |
| `mcp_server.py`, `data_mapping_agent.py` | Earlier versions, kept for reference |

## How to run

1. Put `northbridge_uk_loans.db` and `data_dictionary.csv` in Google Drive under `MyDrive/northbridge/`.
2. In Colab Secrets, add `GEMINI_API_KEY` and `GROQ_API_KEY`, each with Notebook access switched on.
3. Paste `northbridge_colab_app.py` into one Colab cell and run it.

**Never put API keys in any file.** This repo is private because it contains the answer key.

## Results so far

| Who answers | Score |
|---|---|
| Simple search (RAG only) | 8 of 17 |
| AI agent (RAG + agent) | 5 of 5 on the first 5 questions; full 17 to be run |
