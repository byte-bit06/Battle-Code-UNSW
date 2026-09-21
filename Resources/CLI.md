The CLI
unswbc creates a bot project, builds it, plays matches and uploads the result. The commands below are in the order you will need them. unswbc help <command> lists the options for any one of them.

Recommended
unswbc is a Python package. Install uv if you do not have it, open a new shell so it is on your PATH, then install the toolkit. Later, uv tool upgrade unswbc takes the newest version and uv tool install unswbc==0.3.0 pins one.

Raw
Copy Code
uv tool install unswbc
If you don't have uv
pip installs it just as well, given Python 3.11 or newer, and puts unswbc on your PATH. Debian, Ubuntu and Homebrew refuse a plain pip install and say externally-managed-environment; on those, uv is the way.

Raw
Copy Code
pip install unswbc
unswbc
On its own it lists the commands and checks this machine: the Python interpreter, the C and C++ compilers, VS Code and the replay viewer. Anything missing is named with the step that installs it.

Raw
Copy Code
unswbc
unswbc init
Creates a project in c, cpp or python, holding a starter bot and the helper library. The directory defaults to the current one. Maps do not go inside it: they land in a maps/ folder beside the project, which every bot of yours can share.

Raw
Copy Code
unswbc init python mybot
unswbc maps
Adds any bundled map the folder is missing, and leaves your own files alone, so run it after upgrading the toolkit. The folder defaults to maps; name another to choose it, such as unswbc maps ../maps for a project you made in the current directory.

Raw
Copy Code
unswbc maps
unswbc run
Plays one match between two bots on a map and writes a replay. Each bot is a project directory, rebuilt before it plays, and naming the same one twice plays it against itself. Add -v to watch every round, or --sandbox to price a Python bot in CPU points the way the judge does.

Raw
Copied
unswbc run maps/arena.map mybot mybot
unswbc vscode
Installs the replay viewer into VS Code, Cursor or VSCodium, so any .replay file opens in the editor. init already does this when it finds one.

Raw
Copied
unswbc vscode
unswbc auth
Stores the API key from your team page, so this machine may submit. unswbc auth status shows the key in use, and unswbc auth clear removes it.

Raw
Copy Code
unswbc auth set bc_...
unswbc submit
Zips the project and uploads it as a new submission. -n names the version and -d records what changed. See Submitting via website.

Raw
Copy Code
unswbc submit mybot
unswbc log
Prints the errors the toolkit has hit on this machine. Send it with any bug report; API keys are masked.

Raw
Copy Code
unswbc log