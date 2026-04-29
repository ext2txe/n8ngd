At the end of message, always end with the text 'COMPLETED' on the last line to indicate that you are waiting for input, do not output COMPLETED if there is  any processing in progress. Only once waiting for user input. 
Each time that a message results in one of more files being modified, increment the version patch number by one. e.g. 0.1.51 -> 0.1.52, 0.1.52 -> 0.1.53
unless specified otherwise assume that application is cross platform if selected tools permit. In that case use compatible path formats
Applications will always include logging.  
Log file should be placed in the log folder in the Local Application Data Folder (or equivalent) 
There will be a daily logfile with the date (yyyyMMdd) prepended to the app name as the log file name.
Startup log message should include the version number
Clean exit should also write a log message
