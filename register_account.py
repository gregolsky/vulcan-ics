import asyncio
import json
import os

from vulcan import Account
from vulcan import Keystore

async def main():

    keystore = await Keystore.create(device_model="Vulcan API")

    with open("keystore.json", "w") as f:
        f.write(keystore.as_json)

    account = await Account.register(keystore, os.environ['VULCAN_TOKEN'], os.environ['VULCAN_SYMBOL'], os.environ['VULCAN_PIN'])

    with open("account.json", "w") as f:
        f.write(account.as_json)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())