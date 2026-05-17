import socket

HOST = "127.0.0.1"
PORT = 59476

buf = ""

def send(sock, msg): #function that sends a message to the server
    sock.sendall((msg + "\n").encode())

def rline(sock): # fucntion that reads a complete line sent from the server
    global buf
    while "\n" not in buf:
        buf += sock.recv(4096).decode()
    line, buf = buf.split("\n", 1)
    return line.strip()

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # our socket
    sock.connect((HOST, PORT)) # connecting the the host / port

    send(sock, "HELO") # send the HELO message to server 
    rline(sock) # read the response from the server 

    send(sock, "AUTH Ben & Sushi") # Send authorisation to server ( not sure if this is 100% correct)
    rline(sock) # read the response from the server

    while True:
        send(sock, "REDY") # Send the REDY message to the server 
        parts = rline(sock).split() # the server will return the job that is needed to be sechduled

        if parts[0] == "NONE": # will stop if it isn't a job
            break 

        elif parts[0] == "JCPL": # Same here will stop if isn't a job
            continue

        elif parts[0] in ("JOBN", "JOBP"):
            job_id = int(parts[1]) # takes the job id out 
            cpu  = int(parts[3]) # takes the cores out 
            mem = int(parts[4]) # takes the memory out 
            disk   = int(parts[5]) # takes the disk out

            send(sock, f"GETS Capable {cpu} {mem} {disk}")
            # sends a message to the server asking what servers are capable for this job using cpu mem and disk
            data_msg = rline(sock) # server sends back what servers are good               
            data_parts = data_msg.split()

            

            n = int(data_parts[1])

            send(sock, "OK") # Send OK message to server            
            servers = []
            for _ in range(n):
                servers.append(rline(sock).split())

            send(sock, "OK")          
            rline(sock)              

            

            server_type = servers[0][0]
            server_id   = servers[0][1]

            # Print what job is being scheduled 
            print(f"Scheduling job {job_id} → {server_type} {server_id}")
            send(sock, f"SCHD {job_id} {server_type} {server_id}") # Sends the scheduled job
            response = rline(sock) # reads the response from the server 
            print(f"SCHD response: {repr(response)}") # Print the respons from the server 

    send(sock, "QUIT") # Ends the socket
    rline(sock) # Reads what the server says 
    sock.close() # Ends the program

if __name__ == "__main__":
    main()