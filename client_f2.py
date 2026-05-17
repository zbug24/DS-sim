import socket
 
HOST = "127.0.0.1"
PORT = 50000  # Default ds-server port; change if using university servers
 
buf = ""  # Global buffer for reading lines from the server
 
def send(sock, msg):
    """Send a newline-terminated message to ds-server."""
    sock.sendall((msg + "\n").encode())
 
def rline(sock):
    """Read one complete newline-terminated line from ds-server."""
    global buf
    while "\n" not in buf:
        chunk = sock.recv(4096).decode()
        buf += chunk
    line, buf = buf.split("\n", 1)
    return line.strip()
 
def gets_query(sock, query):
    """
    Send a GETS query and return the list of server records.
 
    Server record format from this ds-server build:
      [0] type         - server type name
      [1] id           - server instance ID
      [2] hourlyRate   - cost per hour
      [3] state        - "inactive", "booting", "active", "unavailable"
      [4] curStartTime - simulation time current job started (-1 if none)
      [5] availCores   - cores currently free
      [6] availMem     - memory currently free (MB)
      [7] availDisk    - disk currently free (MB)
      [8] waitingJobs  - jobs waiting in this server's queue
      [9] runningJobs  - jobs currently running on this server
 
    Handles the full DATA -> OK -> records -> OK -> '.' exchange.
    When n=0, ds-server still expects the full OK -> . -> OK exchange.
    """
    send(sock, query)
    data_msg = rline(sock)           # Receive: DATA nRecs recLen
    parts = data_msg.split()
 
    if parts[0] != "DATA":
        return []
 
    n = int(parts[1])
 
    if n == 0:
        send(sock, "OK")             # Acknowledge even with no records
        rline(sock)                  # Read "."
        send(sock, "OK")             # Final acknowledgement
        return []
 
    send(sock, "OK")                 # Acknowledge DATA, request records
    servers = []
    for _ in range(n):
        servers.append(rline(sock).split())
 
    send(sock, "OK")                 # Acknowledge records
    rline(sock)                      # Receive "."
 
    return servers
 
def pick_server(servers, job_cores, job_runtime):
    """
    Improved BFFA scheduler.

    Main improvement:
    - Treats 'idle' servers as immediately available.
    - Uses server cost as a tie-breaker to reduce rental cost.
    - Uses job runtime and queue length to avoid long waits.
    """

    tier1 = []  # active/idle, enough free cores, no queue
    tier2 = []  # booting, enough free cores, no queue
    tier3 = []  # inactive
    tier4 = []  # busy/queued

    for s in servers:
        server_type = s[0]
        server_id = int(s[1])
        hourly_rate = float(s[2])
        state = s[3]
        avail_cores = int(s[5])
        waiting_jobs = int(s[8])
        running_jobs = int(s[9])

        if state in ("active", "idle"):
            if avail_cores >= job_cores and waiting_jobs == 0:
                surplus = avail_cores - job_cores

                # Lower is better:
                # 1. tight fit
                # 2. cheaper server
                # 3. fewer running jobs
                tier1.append((surplus, hourly_rate, running_jobs, server_id, s))
            else:
                queue_score = waiting_jobs * job_runtime + running_jobs * (job_runtime * 0.5)
                tier4.append((queue_score, hourly_rate, server_id, s))

        elif state == "booting":
            if avail_cores >= job_cores and waiting_jobs == 0:
                surplus = avail_cores - job_cores

                # Booting server is not as good as idle/active, but better than cold boot.
                tier2.append((surplus, hourly_rate, running_jobs, server_id, s))
            else:
                queue_score = waiting_jobs * job_runtime + running_jobs * (job_runtime * 0.5)
                tier4.append((queue_score, hourly_rate, server_id, s))

        elif state == "inactive":
            if avail_cores >= job_cores:
                surplus = avail_cores - job_cores

                # For inactive servers, avoid unnecessarily expensive servers.
                tier3.append((surplus, hourly_rate, server_id, s))

    if tier1:
        tier1.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        return tier1[0][4]

    if tier2:
        tier2.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        return tier2[0][4]

    if tier3:
        tier3.sort(key=lambda x: (x[0], x[1], x[2]))
        return tier3[0][3]

    if tier4:
        tier4.sort(key=lambda x: (x[0], x[1], x[2]))
        return tier4[0][3]

    return servers[0]
 
def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Create TCP socket
    sock.connect((HOST, PORT))                                 # Connect to ds-server
 
    # --- Handshake ---
    send(sock, "HELO")
    rline(sock)                    # Receive: OK
 
    send(sock, "AUTH Ben & Sushi")
    rline(sock)                    # Receive: OK
 
    # --- Main scheduling loop ---
    while True:
        send(sock, "REDY")         # Tell ds-server we are ready for the next event
        msg = rline(sock)
        parts = msg.split()
 
        if parts[0] == "NONE":
            # No more jobs will be submitted - simulation is over
            break
 
        elif parts[0] == "JCPL":
            # A job completed - loop back and send REDY to get the next event
            continue
 
        elif parts[0] in ("JOBN", "JOBP"):
            # A new job has been submitted and needs to be scheduled
            # JOBN format: JOBN jobID submitTime cores mem disk estRunTime
            #              [0]  [1]   [2]         [3]  [4]  [5]  [6]
            job_id    = int(parts[1])  # Unique job ID
            job_cores = int(parts[3])  # CPU cores required
            job_mem   = int(parts[4])  # Memory required (MB)
            job_disk  = int(parts[5])  # Disk required (MB)
 
            # Query all servers capable of running this job
            servers = gets_query(sock, f"GETS Capable {job_cores} {job_mem} {job_disk}")
 
            # Pick the best server using BFFA
            job_runtime = int(parts[6])
            chosen = pick_server(servers, job_cores, job_runtime)
            server_type = chosen[0]
            server_id   = chosen[1]
 
            # Schedule the job to the chosen server
            send(sock, f"SCHD {job_id} {server_type} {server_id}")
            rline(sock)            # Receive: OK
 
    # --- End simulation ---
    send(sock, "QUIT")
    rline(sock)                    # Receive: QUIT
    sock.close()
 
if __name__ == "__main__":
    main()