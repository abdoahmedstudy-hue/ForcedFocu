import socket, struct

def extract_ips_from_dns(data: bytes):
    ips = []
    try:
        qdcount, ancount, nscount, arcount = struct.unpack("!HHHH", data[4:12])
        idx = 12
        
        for _ in range(qdcount):
            while idx < len(data) and data[idx] != 0:
                idx += 1 + data[idx]
            idx += 5
            
        for _ in range(ancount):
            if idx >= len(data): break
            # skip name
            if (data[idx] & 0xC0) == 0xC0:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    if (data[idx] & 0xC0) == 0xC0:
                        idx += 2
                        break
                    idx += 1 + data[idx]
                else:
                    idx += 1 # for the 0 byte
            
            if idx + 10 > len(data): break
            rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[idx:idx+10])
            idx += 10
            
            if rtype == 1 and rdlength == 4: # A
                ip = socket.inet_ntoa(data[idx:idx+4])
                ips.append(ip)
            elif rtype == 28 and rdlength == 16: # AAAA
                ip = socket.inet_ntop(socket.AF_INET6, data[idx:idx+16])
                ips.append(ip)
                
            idx += rdlength
    except Exception as e:
        print("error", e)
    return ips

# query google.com
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
query = b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06google\x03com\x00\x00\x01\x00\x01'
s.sendto(query, ("8.8.8.8", 53))
resp, _ = s.recvfrom(4096)
print("IPs:", extract_ips_from_dns(resp))
