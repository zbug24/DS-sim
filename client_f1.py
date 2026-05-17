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
    send(sock, query)
    data_msg = rline(sock)
    parts = data_msg.split()

    if parts[0] != "DATA":
        return []

    n = int(parts[1])

    if n == 0:
        send(sock, "OK")            # Still need to acknowledge even with 0 records
        rline(sock)                 # Still need to read the "."
        send(sock, "OK")            # Still need final acknowledgement
        return []

    send(sock, "OK")
    servers = []
    for _ in range(n):
        servers.append(rline(sock).split())

    send(sock, "OK")
    rline(sock)

    return servers

def pick_server(servers, job_cores, est_run):
    """
    Choose the best server for a job to minimise turnaround time.

    We use the actual server state and queue information to estimate how
    soon each server can start the job, then pick the best option.

    The algorithm classifies servers into four tiers:

    Tier 1 (best) - Active servers with enough free cores to start the job
                    immediately, AND no jobs waiting in their queue.
                    Among these, pick the one with the smallest surplus of
                    free cores (best-fit). This avoids wasting large servers
                    on small jobs, keeping them available for future large
                    jobs and reducing overall waiting time across all jobs.

    Tier 2        - Booting servers with enough free cores and no waiting
                    queue. They will be ready very soon. Among these, pick
                    the smallest that fits (best-fit by cores).

    Tier 3        - Inactive servers. They need to boot but will then be
                    fully free. Among these, pick the smallest that fits,
                    to preserve larger servers for larger jobs.

    Tier 4 (last) - Active servers that are busy (not enough free cores or
                    have a waiting queue). Job must queue behind others.
                    Among these, pick the one with the fewest waiting jobs
                    to minimise expected queue wait time.

    This algorithm is called Best-Fit First Available (BFFA).
    """
    tier1 = []  # Active, free cores >= needed, no queue  (start immediately)
    tier2 = []  # Active, short queue (waiting < 2 jobs)
    tier3 = []  # Booting, free cores >= needed, no queue (start very soon)
    tier4 = []  # Inactive                                (need to boot)
    tier5 = []  # Active but busy or queued               (must wait)

    queue_threshold = 2 if est_run < 300 else 0

    for s in servers:
        state        = s[3]           # "inactive", "booting", "active", etc.
        avail_cores  = int(s[5])      # cores currently free
        waiting_jobs = int(s[8])      # jobs waiting in queue

        if state == "active":
            if avail_cores >= job_cores and waiting_jobs == 0:
                # Can start immediately with no queue - best case
                surplus = avail_cores - job_cores
                tier1.append((surplus, s))
            elif waiting_jobs <= queue_threshold:
                tier2.append((waiting_jobs, s))
            else:
                # Busy or has a queue - job will have to wait
                tier5.append((waiting_jobs, s))

        elif state == "booting":
            if avail_cores >= job_cores:
                # Almost ready, will be free on boot
                surplus = avail_cores - job_cores
                tier3.append((surplus, s))
        
        elif state == "inactive":
            # Server is off but will be fully free once booted
            if avail_cores >= job_cores:
                tier4.append((avail_cores, s))

    # Tier 1: active + free + no queue - pick tightest fit
    if tier1:
        tier1.sort(key=lambda x: x[0])   # Ascending surplus cores
        return tier1[0][1]
    
     # Tier 2: # Active, short queue
    if tier2:
        tier2.sort(key=lambda x: x[0])   # Ascending surplus cores
        return tier2[0][1]

    # Tier 3: booting + free + no queue - pick tightest fit
    if tier3:
        tier3.sort(key=lambda x: x[0])   # Ascending surplus cores
        return tier3[0][1]
  
    # Tier 4: inactive - pick smallest that can fit the job
    if tier4:
        tier4.sort(key=lambda x: x[0])   # Ascending total cores
        return tier4[0][1]
    
    # Tier 5: all busy - pick server with shortest queue
    if tier5:
        tier5.sort(key=lambda x: x[0])   # Ascending waiting jobs
        return tier5[0][1]

    
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
            # JOBN format: JOBN jobID submitTime estRunTime cores mem disk
            #              [0]  [1]   [2]         [3]        [4]  [5]  [6]
            job_id    = int(parts[1])  # Unique job ID
            est_run   = int(parts[2])
            job_cores = int(parts[3])  # CPU cores required
            job_mem   = int(parts[4])  # Memory required (MB)
            job_disk  = int(parts[5])  # Disk required (MB)

            # Query all servers capable of running this job
            servers = gets_query(sock, f"GETS Capable {job_cores} {job_mem} {job_disk}")
            chosen  = pick_server(servers, job_cores, est_run)
           
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
