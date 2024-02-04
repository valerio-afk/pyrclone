![MIT Licence](https://badgen.net/static/license/MIT/blue) ![Python >=3.10](https://badgen.net/badge/python/3.10/blue)

# 🐍☁️PyRclone
A python library wrapping some [rclone](https://rclone.org/) functionality to be accessed seamlessly in your python code. Differently than other similar projects, pyrclone interacts with rclone via ``rc`` API (HTTP protocol).

**This is a work-in-progress library** and currently not available through PIP. You are welcome to download and use it in your own projects (please read carefully licence and disclaimer).

## ⚙️Current Exposed Functionality
PyRclone does not provide use all the functionality that can be accessed via the rc API provided by rclone. Currently, the main exposed features are:

- User authentication via HTTP protocol (optional)
- List of the configured rclone remotes
- List of files
- Checksum calculation (not available for all remotes)
- File copy
- File/Directory deletion
- Transfer status

This library assumes that rclone is already installed and configured in your system.
## 🏃Quick Start

    from pyrclone import rclone
    
    rc = rclone()     #create an istance of the wrapper
    rc.run()          #launches the rclone rc daemon
    rc.list_remotes() # returns a list of remotes

## 🧱API
The constructor takes 5 optional parameters
- ``cmd:`` the command to invoke rclone. Default is ``rclone`` (this assumes rclone binary is in your system path). You can provide an absolute or relative path to the binary.
- ``address:`` address to the rclone HTTP daemon (defaut `localhost`)
- ``port:`` port used by the HTTP daemon (defaut `5572`)
- ``authentication:`` boolean indicating whether to use user authentication (default ``False``)
- ``authenticator:`` If the previous parameter is set to ``True``, you should specify authentication details (e.g., username & password). This can be easily done by making an object of a (sub-)type ``RCloneAuthenticator`` as follows: ``RCloneUserAuthenticator("johndoe", "secretpassword")``. 

The class ``RCloneUserAuthenticator`` is located in ``auth.py``.

Most of the methods are self-explanatory, such as ``ls`` returns the list of files given a path, ``copy_file`` copies a file from source to destination. 

Albeit this class exposes a limited number of functionality, you can use the the method ``make_request`` to take advantage of non-exposed stuff. Further details are provided in [``rclone rc``](https://rclone.org/rc/) documentation.

The method ``make_request`` takes the following parameters:
- ``backend:`` rclone backend.
- ``command:`` specific command within the specified backend
- ``**kwargs:`` a list of parameters that will be provided to rclone via JSON. Just add any keyword arguments and the method will do the rest for you. If all goes well, you will be getting a dictonary representing the JSON output given by rclone.

## ⚠️Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.