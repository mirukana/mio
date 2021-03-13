import shutil
import socket
import subprocess
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Union

from mio.core.types import HttpUrl
from ruamel.yaml import YAML


@dataclass
class SynapseHandle:
    dir:  Path = Path(__file__).parent / "synapse"
    host: str  = field(init=False, default="127.0.0.1")
    port: int  = field(init=False, default=0)


    @property
    def config(self) -> Path:
        return self.dir / "homeserver.yaml"


    @property
    def log(self) -> Path:
        return self.dir / "homeserver.log"


    @property
    def running(self) -> bool:
        return (self.dir / "homeserver.pid").exists()


    @property
    def url(self) -> HttpUrl:
        return f"http://{self.host}:{self.port}"  # type: ignore


    def create(self) -> None:
        self.dir.mkdir(exist_ok=True, parents=True)
        run_command([
            "python3", "-m", "synapse.app.homeserver",
            "--server-name=localhost",
            "--report-stats=no",
            "--generate-config",
            f"--config-path={self.config}",
            f"--data-directory={self.dir}",
        ])

        self.port = find_free_port() if self.port == 0 else self.port

        with edit_yaml(self.config) as config:
            # Remove ::1, it causes problems on systems with IPv6 disabled
            config["listeners"][0]["bind_addresses"] = [self.host]
            config["listeners"][0]["port"]           = self.port

            # Disable rate limits which lead to 429 errors
            no_limits = {"per_second": 9_999_999, "burst_count": 9_999_999}

            config.update({
                "rc_message": no_limits,
                "rc_registration": no_limits,
                "rc_login": {
                    "address": no_limits,
                    "account": no_limits,
                    "failed_attempts": no_limits,
                },
                "rc_admin_redaction": no_limits,
                "rc_joins": {
                    "local": no_limits,
                    "remote": no_limits,
                },
                "rc_3pid_validation": no_limits,
                "rc_invites": {
                    "per_room": no_limits,
                    "per_user": no_limits,
                },
            })

            # Set log file path
            with edit_yaml(config["log_config"]) as log_config:
                log_config["handlers"]["file"]["filename"] = str(self.log)


    def start(self) -> None:
        if self.config.exists():
            with edit_yaml(self.config) as config:
                self.host = config["listeners"][0]["bind_addresses"][0]
                self.port = config["listeners"][0]["port"]
        else:
            self.create()

        if not self.running:
            run_command(["synctl", "start", str(self.config)])


    def stop(self) -> None:
        if self.running:
            run_command(["synctl", "stop", str(self.config)])


    def destroy(self) -> None:
        self.stop()

        if self.dir.exists():
            shutil.rmtree(self.dir)


    def register(self, username: str, password: str = "test") -> None:
        run_command([
            "register_new_matrix_user",
            f"--user={username}",
            f"--password={password}",
            "--no-admin",
            f"--config={self.config}",
            self.url,
        ])


def run_command(cmd: List[str]) -> str:
    process = subprocess.run(cmd, capture_output=True)

    if process.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{process.stderr.decode()}")

    return (process.stdout or b"").decode()


def find_free_port(host: str = "127.0.0.1") -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((host, 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


@contextmanager
def edit_yaml(path: Union[str, Path]) -> Iterator[Dict[str, Any]]:
    path    = Path(path)
    yaml    = YAML()
    content = yaml.load(path)

    yield content

    with open(path, "w") as file:
        yaml.dump(content, file)
