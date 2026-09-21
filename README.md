This project is a local LLM server and set of wrappers designed for privacy and security. The primary working components are a script to initialize a server running your large (or small!) language model of choice with a number of parameters, and a python script to interact with that model.
The script allows users to input prompts, pipe in stdin from system documents, or directly drop in files for assessment. 

The server initialization specifies strict constraints: no network access, read only access, and limited computer resource access.

Dependencies:
The script requires Python 3 and the following:
-JSON
-OS
-RE
-SYS
-urllib.request
-urllib.error


The script includes functions for:

- Reading and checking input data.
- Building a payload for the API request.
- Sending a stream request to the API.
- Handling environment variables and system prompts.

## File Structure

- `llm-client2.py`: The main script.
- `llm-ask6`: A bash script to run the Python script from the current directory.

## License

This project is licensed under the terms of the MIT license.
