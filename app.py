import asyncio
import json
import os
import re
import shutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx
import platform

app = FastAPI()

# index.html 제공
# index.html 제공 및 헬스체크 (Render 지원)
@app.api_route("/", methods=["GET", "HEAD"])
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}

@app.get("/test-ping")
async def test_ping():
    cmd = ["ping", "-c", "1", "8.8.8.8"]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return {
            "PING_CMD": PING_CMD,
            "stdout": stdout.decode(errors="ignore"),
            "stderr": stderr.decode(errors="ignore"),
            "returncode": process.returncode
        }
    except Exception as e:
        return {"error": str(e)}

# 시스템 명령어 존재 여부 확인
PING_CMD = shutil.which("ping")
TRACERT_CMD = shutil.which("tracert") or shutil.which("traceroute")

print(f"System Check: PING_CMD={PING_CMD}, TRACERT_CMD={TRACERT_CMD}")

class IPRequest(BaseModel):
    ip: str

@app.post("/api/ipinfo")
async def get_ip_info(request: IPRequest):
    ip = request.ip
    async with httpx.AsyncClient() as client:
        try:
            # zip, lat, lon 필드 추가
            response = await client.get(f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,lat,lon,isp,as&lang=ko")
            data = response.json()
            if data.get("status") == "success":
                return {
                    "country": data.get("country"),
                    "regionName": data.get("regionName"),
                    "city": data.get("city"),
                    "zip": data.get("zip"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "isp": data.get("isp"),
                    "as": data.get("as"),
                }
            else:
                return {"error": "IP 정보를 찾을 수 없습니다."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

async def ping_loop(websocket: WebSocket, ip: str):
    """지속적으로 ping을 보내고 결과를 웹소켓으로 전송 (1초 간격)"""
    if not PING_CMD:
        await websocket.send_json({"type": "ping", "ms": 0, "status": "Error: ping command not found"})
        return

    while True:
        try:
            is_windows = platform.system().lower() == "windows"
            if is_windows:
                cmd = ["ping", "-n", "1", "-w", "1000", ip]
            else:
                # 리눅스 환경에서는 -W가 초 단위임 (1 = 1초)
                cmd = ["ping", "-c", "1", "-W", "1", ip]
            
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            except FileNotFoundError:
                print(f"Error: Ping command not found at {PING_CMD}. Please ensure it's in your PATH.")
                await websocket.send_json({"type": "ping", "ms": 0, "status": "Error: ping command not found"})
                break
            except Exception as e:
                print(f"Error starting ping subprocess for {ip}: {e}")
                await websocket.send_json({"type": "ping", "ms": 0, "status": f"Error: Failed to start ping ({e})"})
                break

            stdout, stderr = await process.communicate()
            output = stdout.decode("cp949" if is_windows else "utf-8", errors="ignore")
            error_output = stderr.decode("cp949" if is_windows else "utf-8", errors="ignore")
            
            time_match = re.search(r"시간[=<]([0-9]+)ms|time[=<]([0-9]+)ms", output, re.IGNORECASE)
            
            if process.returncode == 0 and time_match:
                ms = int(time_match.group(1) or time_match.group(2))
                status = "Success"
            else:
                ms = 0
                status = "Timeout"
                if error_output:
                    print(f"Ping Command Error for {ip}: {error_output.strip()}")
            
            await websocket.send_json({
                "type": "ping",
                "ms": ms,
                "status": status
            })
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Ping loop general error for {ip}: {e}")
            await asyncio.sleep(1)

async def tracert_loop(websocket: WebSocket, ip: str):
    """Traceroute를 수행하고 홉 정보를 전송한 후 각 홉에 대해 병렬 Ping 수행"""
    if not TRACERT_CMD:
        await websocket.send_json({"type": "tracert", "hops": [{"hop": 1, "ip": "Error", "ms": 0, "status": "traceroute command not found"}]})
        return

    is_windows = platform.system().lower() == "windows"
    
    if is_windows:
        cmd = ["tracert", "-d", "-h", "30", "-w", "1000", ip]
    else:
        cmd = ["traceroute", "-n", "-m", "30", "-w", "1", ip]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        print(f"Error: Traceroute command not found at {TRACERT_CMD}. Please ensure it's in your PATH.")
        await websocket.send_json({"type": "tracert", "hops": [{"hop": 1, "ip": "Error", "ms": 0, "status": "traceroute command not found"}]})
        return
    except Exception as e:
        print(f"Error starting tracert subprocess for {ip}: {e}")
        await websocket.send_json({"type": "tracert", "hops": [{"hop": 1, "ip": "Error", "ms": 0, "status": f"Error: Failed to start tracert ({e})"}]})
        return
    
    hops = []
    hop_regex = re.compile(r"^\s*(\d+)\s+.*?\s+((?:\d{1,3}\.){3}\d{1,3})")
    
    while True:
        line = await process.stdout.readline()
        if not line:
            break
            
        decoded_line = line.decode("cp949" if is_windows else "utf-8", errors="ignore")
        match = hop_regex.search(decoded_line)
        
        if match:
            hop_num = int(match.group(1))
            hop_ip = match.group(2)
            hops.append({"hop": hop_num, "ip": hop_ip})
            
            await websocket.send_json({
                "type": "tracert_hop",
                "hop": hop_num,
                "ip": hop_ip
            })

    await process.wait()
    
    async def hop_ping(hop_ip: str, hop_num: int):
        while True:
            try:
                if is_windows:
                    c = ["ping", "-n", "1", "-w", "1000", hop_ip]
                else:
                    c = ["ping", "-c", "1", "-W", "1", hop_ip]
                
                p = await asyncio.create_subprocess_exec(*c, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, _ = await p.communicate()
                out = stdout.decode("cp949" if is_windows else "utf-8", errors="ignore")
                t_match = re.search(r"시간[=<]([0-9]+)ms|time[=<]([0-9]+)ms", out, re.IGNORECASE)
                
                if p.returncode == 0 and t_match:
                    ms = int(t_match.group(1) or t_match.group(2))
                else:
                    ms = -1  # Timeout
                
                await websocket.send_json({
                    "type": "hop_ping_update",
                    "hop": hop_num,
                    "ip": hop_ip,
                    "ms": ms
                })
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Hop ping loop general error for {hop_ip} (hop {hop_num}): {e}")
                await asyncio.sleep(1)

    ping_tasks = [asyncio.create_task(hop_ping(h["ip"], h["hop"])) for h in hops]
    try:
        while True:
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        for t in ping_tasks:
            t.cancel()

@app.websocket("/ws/{ip}")
async def websocket_endpoint(websocket: WebSocket, ip: str):
    print(f"WebSocket connecting to IP: {ip}")
    await websocket.accept()
    print(f"WebSocket accepted for IP: {ip}")
    
    ping_task = asyncio.create_task(ping_loop(websocket, ip))
    tracert_task = asyncio.create_task(tracert_loop(websocket, ip))
    
    try:
        while True:
            # 클라이언트로부터 메시지를 기다리거나 연결 유지를 위해 대기
            data = await websocket.receive_text()
            print(f"Received from client {ip}: {data}")
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for IP: {ip}")
    except Exception as e:
        print(f"WebSocket unexpected error for {ip}: {e}")
    finally:
        ping_task.cancel()
        tracert_task.cancel()
        print(f"Tasks cancelled for {ip}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
