import socket

HOST = "127.0.0.1"
PORT = 59476  # Default ds-server port; change if using university servers

buf = ""  # Global buffer for reading lines from the server

def send(sock, msg):
    """Send a newline-terminated message to ds-server."""
    sock.sendall((msg + "\n").encode())

def rline(sock):
    """Read one complete newline-terminated line from ds-server."""
    global buf
    while "\n" not in buf:
        buf += sock.recv(4096).decode()
    line, buf = buf.split("\n", 1)
    return line.strip()

def gets_query(sock, query):
    """
    Send a GETS query and return the list of server records.
    Each record is a list of strings:
      [type, id, state, curStartTime, availCores, availMem, availDisk]
    Handles the full DATA -> OK -> records -> OK -> '.' exchange.
    """
    send(sock, query)
    data_msg = rline(sock)          # Receive: DATA nRecs recLen
    n = int(data_msg.split()[1])    # Number of server records coming

    send(sock, "OK")                # Acknowledge DATA, ask for records
    servers = []
    for _ in range(n):
        servers.append(rline(sock).split())

    send(sock, "OK")                # Acknowledge end of records
    rline(sock)                     # Receive: "." (end of transmission)

    return servers

def pick_server(servers, job_cores):
    """
    Choose the best server for a job using our scheduling algorithm.

    The goal is to minimise turnaround time, which means minimising how long
    a job waits before it starts running. We classify each capable server into
    one of four tiers based on how soon it can start the job, then pick the
    best server within the highest available tier.

    Server record fields:
      [0] type         - server type name
      [1] id           - server instance ID
      [2] state        - "inactive", "booting", "active", "unavailable"
      [3] curStartTime - simulation time current job started (-1 if none)
      [4] availCores   - cores currently free
      [5] availMem     - memory currently free
      [6] availDisk    - disk currently free

    Tier 1 (best)  - Active servers with enough free cores to start immediately.
                     Among these, pick the one with the smallest surplus of free
                     cores over what the job needs (best-fit). This avoids
                     wasting large servers on small jobs, keeping them free for
                     future large jobs and reducing overall waiting time.

    Tier 2         - Booting servers with enough free cores. They are almost
                     ready and will start the job very soon. Among these, pick
                     the one with the smallest total core count (smallest fit),
                     again to preserve larger servers for larger jobs.

    Tier 3         - Inactive servers. They need to boot first, but will
                     eventually be free. Among these, pick smallest core count.

    Tier 4 (last)  - Active servers with a job queue (not enough free cores
                     right now). Job must wait for a slot. Pick the first one
                     (matching FAFC-style fallback behaviour).

    This algorithm is called Best-Fit First Available (BFFA).
    """
    tier1 = []  # Active, free cores >= job_cores  (start immediately)
    tier2 = []  # Booting, free cores >= job_cores (start very soon)
    tier3 = []  # Inactive, total cores >= job_cores (need to boot)
    tier4 = []  # Active but queued (must wait for a running job to finish)

    for s in servers:
        state       = s[2]
        avail_cores = int(s[4])

        if state == "active":
            if avail_cores >= job_cores:
                # Can start immediately - track surplus cores for best-fit ranking
                surplus = avail_cores - job_cores
                tier1.append((surplus, s))
            else:
                # Active but no room right now - job will be queued
                tier4.append(s)

        elif state == "booting":
            # Server is booting; availCores reflects what will be free on boot
            if avail_cores >= job_cores:
                tier2.append((avail_cores, s))

        elif state == "inactive":
            # Server is off; availCores equals total cores when inactive
            if avail_cores >= job_cores:
                tier3.append((avail_cores, s))

    # Tier 1: active + immediately available - pick smallest surplus (best-fit)
    if tier1:
        tier1.sort(key=lambda x: x[0])  # Sort by surplus cores ascending
        return tier1[0][1]

    # Tier 2: booting - pick smallest total cores (smallest server that fits)
    if tier2:
        tier2.sort(key=lambda x: x[0])  # Sort by availCores ascending
        return tier2[0][1]

    # Tier 3: inactive - pick smallest total cores (smallest server that fits)
    if tier3:
        tier3.sort(key=lambda x: x[0])  # Sort by availCores ascending
        return tier3[0][1]

    # Tier 4: all capable servers are busy - fall back to first capable (FAFC-style)
    if tier4:
        return tier4[0]

    # Should never reach here since GETS Capable guarantees at least one result
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
        parts = rline(sock).split()

        if parts[0] == "NONE":
            # No more jobs will be submitted - simulation is over
            break

        elif parts[0] == "JCPL":
            # A job completed - loop back and send REDY to get the next event
            continue

        elif parts[0] in ("JOBN", "JOBP"):
            # A new job has been submitted and needs to be scheduled
            # JOBN format: JOBN submitTime jobID estRunTime cores mem disk
            #              [0]  [1]         [2]   [3]        [4]   [5] [6]
            job_id    = int(parts[2])  # Unique job ID
            job_cores = int(parts[4])  # CPU cores required
            job_mem   = int(parts[5])  # Memory required (MB)
            job_disk  = int(parts[6])  # Disk required (MB)

            # Query all servers capable of running this job (sufficient total resources)
            servers = gets_query(sock, f"GETS Capable {job_cores} {job_mem} {job_disk}")

            # Pick the best server using our BFFA algorithm
            chosen      = pick_server(servers, job_cores)
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
