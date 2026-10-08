import asyncio
import sys
import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt

from whatsapp_web import WhatsAppWebController
from agent import UniversalAIAgent
from voice import VoiceEngine

console = Console()


def display_hub_banner():
    table = Table(title="🤖 Universal AI Personal Assistant - Connected Hub", border_style="cyan")
    table.add_column("Application", style="bold yellow")
    table.add_column("Status", justify="center")
    table.add_column("Example Command", style="dim")

    table.add_row("💬 WhatsApp", "[green]✓ Ready[/green]", "Text +919390108691 saying hey / Summarize group")
    table.add_row("📸 Screenshots", "[green]✓ Ready[/green]", "Take a screenshot and WhatsApp it to Kiran Sai")
    table.add_row("📁 File Sharing", "[green]✓ Ready[/green]", "Send resume.pdf to Alex on WhatsApp")
    table.add_row("📧 Gmail", "[green]✓ Ready[/green]", "Check unread emails / Email alex@test.com")
    table.add_row("📷 Instagram", "[green]✓ Ready[/green]", "Send Instagram DM to @elonmusk saying hi")
    table.add_row("🎙️ Voice Control", "[green]✓ Ready[/green]", "Type 'voice' or 'v' to speak via microphone")

    console.print(table)
    console.print(
        "[yellow]💡 Tip:[/yellow] Type [bold green]'voice'[/bold green] (or [bold green]'v'[/bold green]) to speak commands hands-free, or type normally!\n"
    )


async def main():
    display_hub_banner()

    wa_controller = WhatsAppWebController()
    
    with console.status("[bold green]Connecting to WhatsApp & loading tools...[/bold green]"):
        try:
            await wa_controller.initialize(headless=False)
        except Exception as e:
            console.print(f"[bold red]Failed to start WhatsApp Web:[/bold red] {e}")
            return

    console.print("[bold green]✓ All systems connected and ready![/bold green]\n")
    agent = UniversalAIAgent(wa_controller)
    voice_engine = VoiceEngine(tts_enabled=True)

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You (type command or 'v' for voice)[/bold cyan]").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                console.print("[dim]Closing Assistant...[/dim]")
                break

            # Voice command activation
            if user_input.lower() in ("voice", "v", "mic", "speak"):
                console.print("[bold yellow]🎙️ Microphone active... Speak your command now![/bold yellow]")
                voice_text = voice_engine.listen("🎙️ Listening for your voice...")
                if not voice_text:
                    console.print("[red]No speech detected. Please try again.[/red]")
                    continue
                console.print(f"[bold cyan]You (Voice):[/bold cyan] [green]\"{voice_text}\"[/green]")
                user_input = voice_text

            if user_input.lower() in ("contacts", "show contacts", "list contacts"):
                contacts = agent.contacts.get_all()
                table = Table(title="Saved Contacts", border_style="green")
                table.add_column("Name", style="bold yellow")
                table.add_column("Phone Number", style="cyan")
                table.add_column("Notes", style="dim")
                for c in contacts:
                    table.add_row(c.get("name", ""), f"+{c.get('phone', '')}", c.get("notes", ""))
                console.print(table)
                continue

            with console.status("[bold green]AI Assistant executing action...[/bold green]", spinner="dots"):
                result = await agent.run_instruction(user_input)

            # Display actions
            actions = result.get("actions", [])
            for action in actions:
                res = action.get("result", {})
                success = res.get("success", True) if isinstance(res, dict) else True
                status_str = "[bold green]DONE[/bold green]" if success else "[bold red]FAILED[/bold red]"
                
                details = ""
                if isinstance(res, dict):
                    if "recipient_display" in res:
                        details += f"Recipient: [bold]{res['recipient_display']}[/bold]\n"
                    if "file_path" in res:
                        details += f"File: [bold]{res['file_path']}[/bold]\n"
                    if "to" in res:
                        details += f"Email To: [bold]{res['to']}[/bold]\n"
                    if "error" in res:
                        details += f"Error: [red]{res['error']}[/red]\n"

                console.print(Panel(details.strip() or "Executed successfully.", title=f"Action: {action.get('tool')} [{status_str}]", border_style="green" if success else "red"))

            reply = result.get("reply", "")
            if reply:
                console.print(f"\n[bold green]AI Assistant:[/bold green] {reply}")
                # Optional voice readback for hands-free mode
                if user_input == voice_text if 'voice_text' in locals() else False:
                    voice_engine.speak(reply)

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    await wa_controller.close()


if __name__ == "__main__":
    asyncio.run(main())
