import asyncio

from typing_extensions import Self, AsyncIterable
from typing import Union, Tuple, Any, List, Dict
from subprocess import Popen, PIPE
from aiohttp import ClientSession, BasicAuth, ClientResponseError, ClientTimeout
from aiohttp.client_exceptions import ClientConnectorError
from .auth import RCloneAuthenticator
from .jobs import RCloneJob, RCloneJobStats, RCJobStatus
import json
import os


class rclone:

    def __init__(this, *,
                 cmd: str = "rclone",
                 address: str = "localhost",
                 port: int = 5572,
                 authentication: bool = False,
                 authenticator: Union[RCloneAuthenticator | None] = None
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

        this._running_server: Union[Popen | None] = None
        this._session: Union[ClientSession | None] = None
        this._transferring_jobs:List[int] = []
        this._transferring_jobs_last_update:Dict[int,Union[RCloneJob|None]] = dict()

        # this._debug = open('debug.txt','w')

    async def __aenter__(this) -> Self:
        this.run()
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
            args = {"base_url": f"http://{this._address}:{this._port}", "timeout":ClientTimeout(total=10)}

            if this._auth is not None:
                auth = BasicAuth(login=this._auth.username, password=this._auth.passoword)
                args['auth'] = auth

            this._session = ClientSession(**args)

        return this._session

    async def make_request(this,
                           backend: str,
                           command: str,
                           **kwargs) -> Any:
        '''
        Make a request to the RClone Daemon
        :param backend: RClone backend
        :param command: Supported command within the backend
        :param kwargs: Anything supported by backend/command
        :return: A dictionary representing the json response provided by RClone
        '''
        # this._debug.write(f"\nMaking request {backend}/{command}\n")
        # this._debug.write(f"Args {kwargs}\n")

        async with this._http_session.post(f"/{backend}/{command}", ssl=False, json=kwargs) as response:

            content = await response.text(encoding="utf-8")
            if response.status == 200:
                # this._debug.write(f"Response {content}\n")
                return json.loads(content)
            else:
                raise ClientResponseError(response.request_info, response.history, message=content)

    async def ls(this, root: str, path: str, recursive: bool = False) -> Any:
        '''
        Return the list of files within root at the given Path

        Raises `FileNotFoundError` if the root/path doesn't exist
        Raises ClientResponseError for any issues related to client/server connection

        :param root: An RClone remote or a local path
        :param path: a path relative from root
        :param recursive: If TRUE, runs a recursive listing of all files in root/path
        :return: A list containing the content of the directory
        '''

        opt = {}

        if recursive:
            opt['recurse'] = True

        path = path.lstrip("./")  # rclone doesn't like paths startign with . or / (or both!)

        try:
            data = await this.make_request("operations",
                                           "list",
                                           fs=root,
                                           remote=path,
                                           opt=opt)
            return data['list']

        except ClientResponseError as err:
            if "directory not found" in err.message:
                raise FileNotFoundError(f"{os.path.join(root, path)} was not found")
            else:
                raise err

    async def exists(this, root: str, path: str) -> bool:
        '''
        Check if the provided file/directory exists

        :param root: An RClone remote or a local path
        :param path: a path relative from root
        :return: TRUE if the file exists, FALSE otherwise
        '''

        return (await this.stat(root, path)) is not None

    async def stat(this, root: str, path: str) -> Any:
        '''
        Give information about the supplied file or directory

        :param root: An RClone remote or a local path
        :param path: a path relative from root
        :return: A json containing information about the file/directory, None otherwise
        '''

        data = await this.make_request("operations",
                                       "stat",
                                       fs=root,
                                       remote=path)
        return data['item']

    async def list_remotes(this):
        '''
        Return the list of remotes

        Raises ClientResponseError for any issues related to client/server connection

        :return:
        '''

        d = await this.make_request('config', 'dump', long=True)

        remotes = []

        for k in d:
            remotes.append((d[k]['type'], f"{k}:"))

        return remotes

    async def checksum(this, path: str, hash: str = "md5", remote: bool = False) -> Union[str|None]:
        '''
        Calculate the checksum of a file. This command doesn't use remote control as this command is only available
        from the classic comamnd line. Why? Dunno!

        :param path: Path to the file to get its checksum
        :param hash: The list of supported hashes is here: https://rclone.org/commands/rclone_hashsum/
        :param remote: Remotes might not support the calculation of hashes. Hence, files need to be dowloaded.
                       Set this parameter TRUE wisely as some cloud storage services can limit download bandwidth
        :return:a string representing the hash of the file
        '''

        args = ["hashsum", hash, path]

        if remote:
            args.append("--download")


        proc = await asyncio.create_subprocess_exec(this._cmd, *args,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)

        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            return stdout.decode().split(" ")[0]




    async def copy_file(this, src_root, src_path, dst_root, dst_path) -> int:
        '''
        Copy a file

        :param src_root: Source root path
        :param src_path: Source path to filename
        :param dst_root: Destination root path
        :param dst_path: Destination path to filename
        :return:
        '''
        request_data = {
            "srcFs": src_root,
            "srcRemote": src_path,
            "dstFs": dst_root,
            "dstRemote": dst_path,
            "_async": "true"
        }

        response = await this.make_request("operations", "copyfile", **request_data)

        id = response['jobid']
        this._transferring_jobs.append(id)

        return id

    async def rmdir(this, root: str, path: str, *,  asynch = False) -> Self:
        '''
        Delete the provided directory (it must be empty)

        :param root: An RClone remote or a local path
        :param path: a path relative from root
        :param asynch: launch this task asynchronously (rclone perspective)
        :return: This object
        '''

        await this.make_request("operations",
                                "rmdir",
                                fs=root,
                                remote=path,
                                _async=asynch)
        return this

    async def delete_file(this, root: str, path: str, *,  asynch = False) -> Self:
        '''
        Delete a specific file

        :param root: An RClone remote or a local path
        :param path: a path relative from root
        :param asynch: launch this task asynchronously (rclone perspective)
        :return: This object
        '''

        await this.make_request("operations",
                                "deletefile",
                                fs=root,
                                remote=path,
                                _async=asynch)
        return this

    @property
    async def jobs(this) -> AsyncIterable[Tuple[int,RCJobStatus]]:

        rclone_current_jobs = await this.get_rclone_job_ids()

        for jobid in this._transferring_jobs:

            if jobid in rclone_current_jobs:
                this._transferring_jobs_last_update.setdefault(jobid,None)

                try:
                    job_status = await this.get_job_status(jobid)
                    this._transferring_jobs_last_update[jobid] = job_status
                except (ClientResponseError,asyncio.TimeoutError):
                    ...
                    #job_status = this._transferring_jobs_last_update[jobid]

            job_status = this._transferring_jobs_last_update[jobid]

            if job_status is not None:
                status = job_status.status
            else:
                status = RCJobStatus.NOT_STARTED

            yield jobid,status

    async def get_rclone_job_ids(this) -> List[int]:
        request = await this.make_request("job","list")

        return [int(x) for x in request['jobids']]



    async def has_finished(this) -> bool:
        async for id,status in this.jobs:
            if status not in [RCJobStatus.FINISHED, RCJobStatus.FAILED]:
                return False

        return True


    async def get_job_status(this, id: int) -> RCloneJob:
        '''
        Get the status of a job that is transferring a file
        Differently than the `get_job_status`, this method retrieves more detailed information about the file
        transferring, such as bytes transferred, transfer speed, etc.

        :param id: Job id to get the information from
        :return: An RCloneTransferJob object
        '''
        response_status = await this.make_request("job", "status", jobid=id)
        job = RCloneJob.from_json(response_status)

        response_stats = await this.make_request("core", "stats", group=f"job/{id}")

        if 'transferring' in response_stats.keys():
            stats = RCloneJobStats.from_json(response_stats['transferring'][0])
            job.stats = stats

        return job


    async def get_group_list(this) -> AsyncIterable[str]:
        response = await this.make_request("core","group-list")

        if ("groups" in response) and (response["groups"] is not None):
            for x in response["groups"]:
                yield x

    async def delete_group_stats(this,group_id:str) -> bool:
        response = await this.make_request("core","stats-delete",group=group_id)

        return len(response) == 0

    def get_last_status_update(this, jobid) -> Union[RCloneJobStats | None]:
        return this._transferring_jobs_last_update[jobid] if jobid in this._transferring_jobs_last_update.keys() else None

    #
    def clean_terminated_jobs(this) -> Self:
        '''
        Clean the terminated jobs from the cache

        :return: This object
        '''

        id_to_remove = []

        for jobid,last_updates in this._transferring_jobs_last_update.items():
            if last_updates.status in [RCJobStatus.FINISHED,RCJobStatus.FAILED]:
                id_to_remove.append(jobid)

        for jobid in id_to_remove:
            del this._transferring_jobs_last_update[jobid]
            this._transferring_jobs.remove(jobid)

        return this

    async def stop_job(this, jobid: int) -> bool:
        '''
        Allows to stop a specific job
        :param jobid: The job id to stop

        :return: TRUE if successful, FALSE otherwise
        '''
        response = await this.make_request("job", "stop", jobid=jobid)

        return len(response) == 0 # in case of success, rclone returns an empty json (weird, but it's what it is)

    async def stop_pending_jobs(this) -> Self:
        '''
        Stop all pending jobs

        :return: This object
        '''
        async for id,status in this.jobs:
            if status in [RCJobStatus.NOT_STARTED, RCJobStatus.IN_PROGRESS]:
                await this.stop_job(id)

                # sendign the command to stop a job doesn't mean it gets done immediately
                # to avoid race conditions, better double check if it gets stopped for sure
                finished = False
                while not finished:
                    stats = await this.get_job_status(id)
                    finished = stats.finished


        return this

    def run(this) -> Self:
        '''
        Run the rclone remote control daemon
        This method is intentionally blocking

        :return: The object itself
        '''


        cmd = [
            this._cmd,
            "rcd",
            "--rc-addr", f"{this._address}:{this._port}",
            "--log-level", "INFO",
            "--log-file", "rclone.log"
        ]

        if (this._auth is None):
            cmd.append("--rc-no-auth")
        else:
            cmd += this._auth.cl_arguments

        this._running_server = this._running_server = Popen(
            cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE
        )

        return this

    async def is_ready(this) -> bool:
        try:
            await this.make_request("rc","noop")
            return True
        except ClientConnectorError:
            return False


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

        await this.make_request("core", "quit")
        await this._http_session.close()

        try:
            this.kill()
            return this
        except ChildProcessError:
            ...  # If the daemon was run externally, ie not from this object, it will raise an exception. Nothing to worry about
