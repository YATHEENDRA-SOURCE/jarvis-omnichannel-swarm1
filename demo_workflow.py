# =====================================================================
# J.A.R.V.I.S. INTERVIEWER DEMO WORKFLOW & SCRIPT
# Run: .\venv\Scripts\python.exe demo_workflow.py
# =====================================================================
import asyncio
import os
import sys
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from dotenv import load_dotenv

load_dotenv()
console = Console()

async def run_demo():
    console.print(Panel.fit(
        "[bold cyan]J.A.R.V.I.S. OMNI-CHANNEL AI SWARM[/bold cyan]\n"
        "[italic dim]Interactive Engineering Demo for Technical Interviewers[/italic dim]",
        border_style="cyan"
    ))

    # Check Environment
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red][!] ERROR: GEMINI_API_KEY is not set in .env[/bold red]")
        sys.exit(1)

    console.print("[bold green][✓] Gemini API Key Detected.[/bold green]")
    console.print("[dim]Initializing UniversalAIAgent and Sub-Agent Swarm...[/dim]")

    from agent import UniversalAIAgent
    from whatsapp_web import WhatsAppWebController
    
    # Initialize agent without launching heavy WhatsApp browser for quick CLI demo
    agent = UniversalAIAgent(wa_controller=None)

    table = Table(title="Swarm Units Online", border_style="blue")
    table.add_column("Agent Codename", style="bold cyan")
    table.add_column("Subsystem", style="yellow")
    table.add_column("Key Operations", style="white")

    table.add_row("F.R.I.D.A.Y.", "CommAgent", "WhatsApp, Calls, Gmail, Instagram DMs")
    table.add_row("U.L.T.R.O.N.", "SystemAgent", "Volume Mixer, Wi-Fi, File Explorer, Math")
    table.add_row("S.T.A.R.K.", "DevAgent", "Autonomous Code Writing, VS Code Workspace")
    table.add_row("J.O.C.A.S.T.A.", "DocsAgent", "Notepad Dictation, Word .docx, Weather")
    table.add_row("R.H.O.D.E.Y.", "PhoneAgent", "ADB Unlock, Ad-Bypass YouTube, Spotify Play/Stop")
    table.add_row("E.D.I.T.H.", "VisionAgent", "Screen Multimodal Vision, Coordinates Click")

    console.print(table)
    console.print("\n[bold yellow]Ready for live demonstration.[/bold yellow]\n")

    demo_tasks = [
        ("1. System OS Control", "Set system volume to 65 percent and tell me what the volume is."),
        ("2. Weather & Docs", "What is the weather in Hyderabad today?"),
        ("3. Code Engineering", "Write a Python script that calculates Fibonacci numbers and open it."),
        ("4. Phone Unlock / Media", "Unlock my phone and play Starboy on YouTube avoiding ads."),
    ]

    console.print("[bold]Available Demo Scenarios:[/bold]")
    for idx, (title, query) in enumerate(demo_tasks, 1):
        console.print(f"  [cyan]{idx}.[/cyan] [bold]{title}[/bold] -> [italic]\"{query}\"[/italic]")
    console.print("  [cyan]5.[/cyan] [bold]Custom Command[/bold] -> Enter your own instruction")
    console.print("  [cyan]0.[/cyan] [bold]Exit Demo[/bold]\n")

    while True:
        choice = input("Select a scenario (0-5) [Enter to test Scenario 1]: ").strip()
        if not choice:
            choice = "1"
        if choice == "0":
            console.print("[cyan]Exiting demo. Goodbye, Sir.[/cyan]")
            break

        if choice in ["1", "2", "3", "4"]:
            user_instruction = demo_tasks[int(choice) - 1][1]
        elif choice == "5":
            user_instruction = input("Enter custom instruction: ").strip()
            if not user_instruction:
                continue
        else:
            console.print("[red]Invalid choice.[/red]")
            continue

        console.print(f"\n[bold green]User Instruction:[/bold green] \"{user_instruction}\"")
        console.print("[dim]Dispatching to Master Swarm Orchestrator (Gemini)...[/dim]")
        
        t0 = time.time()
        res = await agent.run_instruction(user_instruction)
        dt = time.time() - t0

        console.print(f"\n[bold magenta]Execution Completed in {dt:.2f}s[/bold magenta]")
        console.print(Panel(
            f"[bold cyan]J.A.R.V.I.S.:[/bold cyan] {res.get('reply', 'No reply')}",
            title="Agent Response",
            border_style="green"
        ))

        actions = res.get("actions", [])
        if actions:
            console.print("[bold]Tools Dispatched:[/bold]")
            for a in actions:
                console.print(f"  - [yellow]{a.get('tool')}[/yellow] with args {a.get('args')}")
        console.print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(run_demo())
