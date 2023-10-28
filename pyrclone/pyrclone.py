import asyncio

from typing_extensions import Self
from typing import Union, List, Any
from pyrclone.auth import RCloneAuthenticator
from pyrclone.jobs import RCloneJob, RCloneTransferJob
from subprocess import Popen, PIPE
from aiohttp import ClientSession, BasicAuth, ClientResponseError
import json
import os

class rclone:

    def __init__(this,*,
                 cmd:str="rclone",
                 address:str = "localhost",
                 port:int=5572,
                 authentication:bool = False,
                 authenticator:Union[RCloneAuthenticator|None]=None
                ):
        '''
        RClone remote controller class. It either uses an already running rclone deamon, or starts its own via the
        `run` method

        Raises a ValueError when `authentication` is True and no authenticator was provided

        :param cmd: rclone command. If rclone binaries are in system Path, the string `rclone` is enough.
                    Alternatively, a full path to the binary should be provided.

        :param address: IP address of the server (either to connect or bind)
        :param port: Port where the server (will) listen
        :param authentication: TRUE if authentication is used, otherwise FALSE
        :param authenticator: An RCloneAuthenticator object
        '''


        this._cmd = cmd
        this._address = address
        this._port = port
        this._auth = None

        if authentication:
            if authenticator is None:
                ValueError("You must provide an authenticator if the parameter `authentication` is TRUE.")

            this._auth = authenticator

        this._running_server:Union[Popen|None]=None
        this._session: Union[ClientSession|None] = None
        this._pending_jobs:List[int] = []

    async def __aenter__(this) -> Self:
        await this.run()
        return this

    async def __aexit__(this, exc_type, exc_val, exc_tb) -> bool:
        await this.quit()
        return exc_type is None



    @property
    def _http_session(this) -> ClientSession:
        '''
        Returns the current HTTP session
        :return: A ClientSession object
        '''
        if this._session is None:
            args = { "base_url": f"http://{this._address}:{this._port}"}

            if this._auth is not None:
                auth = BasicAuth(login=this._auth.username, password=this._auth.passoword)
                args['auth'] = auth

            this._session = ClientSession(**args)

        return this._session

    async def make_request(this,
                           backend:str,
                           command:str,
                           **kwargs) -> Any:
        '''
        Make a request to the RClone Daemon
        :param backend: RClone backend
        :param command: Supported command within the backend
        :param kwargs: Anything supported by backend/command
        :return: A dictionary representing the json response provided by RClone
        '''
        async with this._http_session.post(f"/{backend}/{command}",ssl=False,json=kwargs) as response:
            content = await response.text(encoding="utf-8")
            if response.status == 200:
                return json.loads(content)
            else:
                raise ClientResponseError(response.request_info, response.history, message=content)

    async def ls(this, root:str, path:str) -> Any:
        '''
        Return the list of files within root at the given Path

        Raises `FileNotFoundError` if the root/path doesn't exist
        Raises ClientResponseError for any issues related to client/server connection

        :param root: An RClone remote or a local path
        :param path: a path relative from root
        :return: A list containing the content of the directory
        '''

        try:
            data = await this.make_request("operations",
                                           "list",
                                           fs=root,
                                           remote=path)
            return data['list']

        except ClientResponseError as err:
            if "directory not found" in err.message:
                raise FileNotFoundError(f"{os.path.join(root,path)} was not found")
            else:
                raise err

    async def list_remotes(this):
        '''
        Return the list of remotes

        Raises ClientResponseError for any issues related to client/server connection

        :return:
        '''

        d = await this.make_request('config','dump', long=True)

        remotes = []

        for k in d:
            remotes.append((d[k]['type'], f"{k}:"))

        return remotes

    async def copy_file(this, src_root, src_path, dst_root,dst_path) -> int:
        request_data={
                    "srcFs": src_root,
                    "srcRemote" : src_path,
                    "dstFs" : dst_root,
                    "dstRemote" : dst_path,
                    "_async" : "true"
        }

        response = this.make_request("operations","copyfile", **request_data)

        id = response['jobid']
        this._pending_jobs.append(id)

        return id

    async def get_job_status(this, id:int) -> RCloneJob:
        response = await this.make_request("job","status",jobid=id)

        return RCloneJob.from_json(response)

    async def get_transfer_status(this, id: int) -> RCloneTransferJob:
        response_status = await this.make_request("job", "status", jobid=id)
        response_stats = await this.make_request("core", "stats", group=f"job/{id}")

        d = {**response_status, **response_stats}

        return RCloneTransferJob.from_json(d)

    @property
    async def jobs(this):
        for id in this._pending_jobs:
            yield this.get_transfer_status(id)


    async def run(this) -> Self:
        '''
        Run the rclone remote control daemon
        :return: The object itself
        '''
        cmd = [
            this._cmd,
            "rcd",
            "--rc-addr", f"{this._address}:{this._port}"
        ]

        if (this._auth is None):
            cmd.append("--rc-no-auth")
        else:
            cmd+=this._auth.cl_arguments


        this._running_server = this._running_server = Popen(
            cmd , stdin=PIPE, stdout=PIPE, stderr=PIPE
        )

        await asyncio.sleep(0.1)

        return this

    def kill(this) -> Self:
        '''
        Kill the server. This method should be used only when the current object launched the daemon AND it is
        unresponsive

        Raises a ChildProcessError if the daemon was not launched by the object itself

        :return: The object itself
        '''

        if this._running_server is None:
            raise ChildProcessError("Unable to kill a process that was not run before.")

        this._running_server.kill()

        # The stdout of the process must be read in full after killing it, otherwise the process will turn in a
        # zombie process (at least, in a POSIX environment).
        this._running_server.communicate()

        this._running_server = None

        return this

    async def quit(this) -> Self:
        '''
        Quit nicely the server
        :return: The object itself
        '''

        await this.make_request("core","quit")
        await this._http_session.close()

        try:
            this.kill()
            return this
        except ChildProcessError:
            ...  # If the daemon was run externally, ie not from this object, it will raise an exception. Nothing to worry about
