import asyncio
import sys
from whatsapp_web import WhatsAppWebController
from agent import WhatsAppPersonalAgent


async def main():
    if len(sys.argv) < 2:
        print("Usage: python send_one.py \"<your instruction>\"")
        print("Example: python send_one.py \"Send +919390108691 a message saying hey\"")
        return

    instruction = " ".join(sys.argv[1:])
    print(f"Executing: '{instruction}'...")

    controller = WhatsAppWebController()
    await controller.initialize(headless=False)
    
    agent = WhatsAppPersonalAgent(controller)
    result = await agent.run_instruction(instruction)
    
    print("\nResult:")
    print(result.get("reply", "No reply generated."))
    
    await asyncio.sleep(2)
    await controller.close()


if __name__ == "__main__":
    asyncio.run(main())
