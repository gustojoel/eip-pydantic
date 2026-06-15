# pyright: reportUnusedImport=false

import os

from dotenv import load_dotenv

from eip_pydantic import Session
from eip_pydantic.models.base import SolidServerModel
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet



def main() -> Session:
    load_dotenv()
    host = os.environ["EIP_HOST"]
    username = os.environ["EIP_USERNAME"]
    password = os.environ["EIP_PASSWORD"]
    verify = os.environ.get("EIP_VERIFY", "true").lower() != "false"

    print(f"Connecting to https://{host}/ (verify={verify})")

    return Session(host, username, password, verify=verify)


if __name__ == "__main__":
    session = main()
