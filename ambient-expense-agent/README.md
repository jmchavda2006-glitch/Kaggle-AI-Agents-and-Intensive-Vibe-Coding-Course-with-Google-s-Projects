# 🛡️ EXPENSEGUARD: Enterprise Multi-Agent Expense Triage Console

An enterprise-grade async transaction validation system built with **Spec-Driven Development (SDD)** guidelines. This console orchestrates multiple specialized AI agents under a strict zero-trust Policy Server architecture, implementing regionalized Human-in-the-Loop (HITL) risk containment for elevated transaction brackets.

Developed as a Grand Capstone Project for the **Kaggle 5-Day AI Agents Intensive with Google** (June 2026).

---

## 🚀 Key Architectural Features
- **High-Fidelity Production Dashboard:** A premium glassmorphic dark-mode web UI with embedded live system diagnostic streams (`CPU Load`, `Throughput`).
- **Asynchronous 4-Stage Triage Pipeline:** Natural language inputs are continuously streamed across an immutable verification funnel:
  $$\text{Policy Gate} \longrightarrow \text{AI Parser} \longrightarrow \text{Triage Guard} \longrightarrow \text{Committer}$$
- **Zero-Trust Microservice Routing:** Requests are verified against a decoupled secure `Policy Server` that dynamically maps role authorization parameters.
- **Regionalized HITL Guardrails:** Intercepts high-value items matching or exceeding **₹10,000 (INR)**, flagging them as an *Elevated Risk* and halting code state transitions until manual supervisor authorization is granted.

---

## 🛠️ Complete Local Setup & Installation Guide

Follow these sequential steps to configure and boot the entire multi-service application environment locally on your workstation.

### 1. Clone the Workspace Repository
Clone the repository and navigate directly into the project directory root:
bash
git clone [https://github.com/jmchavda2006-glitch/Kaggle-AI-Agents-and-Intensive-Vibe-Coding-Course-with-Google-s-Projects.git](https://github.com/jmchavda2006-glitch/Kaggle-AI-Agents-and-Intensive-Vibe-Coding-Course-with-Google-s-Projects.git)
cd Kaggle-AI-Agents-and-Intensive-Vibe-Coding-Course-with-Google-s-Projects/ambient_expense_agent]

### 2. Configure Environment Variables (Security Isolation)
Create a new file named exactly .env in the root of the ambient_expense_agent/ directory and add your configurations:
Obtain your API key directly from Google AI Studio
GEMINI_API_KEY=your_actual_gemini_api_key_here
POLICY_SERVER_URL=[http://127.0.0.1:8000](http://127.0.0.1:8000)

### 3. Initialize Python Virtual Environment & Dependencies

Initialize virtual environment folder
python -m venv venv

Activate the virtual runtime context <br><br>
On Windows (PowerShell):<br>
.\venv\Scripts\Activate.ps1<br><br>
On macOS/Linux:<br>
source venv/bin/activate<br><br>

Upgrade package installer and compile system requirements<br><br>
pip install --upgrade pip<br>
pip install -r requirements.txt<br>

### 4. Fire Up the Core Orchestration Microservices
Terminal A: Launch the Security Policy Server<br>
python policy_server.py<br><br>
Terminal B: Launch the Web Console Application<br>
python web_server.py

### 5. Run Automated Architecture Evaluations
adk eval run --config eval_config.json
