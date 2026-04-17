import asyncio
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx
import platform
import sys
import webbrowser
from threading import Timer

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only open browser if not running in a container or cloud environment
    is_cloud = os.environ.get("DOCKER_CONTAINER") or os.environ.get("RENDER") or os.environ.get("RAILWAY")
    if not is_cloud:
        port = int(os.environ.get("PORT", 8000))
        url = f"http://127.0.0.1:{port}"
        print(f"==================================================")
        print(f"🚀 EXANET Ping Monitor Pro is starting!")
        print(f"🌐 Opening browser at: {url}")
        print(f"==================================================")
        # Give the server a little more time to initialize
        Timer(2.5, lambda: webbrowser.open(url)).start()
    yield

app = FastAPI(lifespan=lifespan)

@app.api_route("/", methods=["GET", "HEAD"])
async def get_index():
    index_path = resource_path("index.html")
    with open(index_path, "r", encoding="utf-8") as f:
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

class VerifyRequest(BaseModel):
    password: str

@app.post("/api/verify_password")
async def verify_password(request: VerifyRequest):
    # Password set to 0320 per user request
    if request.password == "0320":
        return {"success": True}
    return {"success": False}

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

async def ping_loop(websocket: WebSocket, ip: str, send_lock: asyncio.Lock):
    """지속적으로 ping을 보내고 결과를 웹소켓으로 전송 (1초 간격)"""
    if not PING_CMD:
        async with send_lock:
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
            
            async with send_lock:
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

async def tracert_loop(websocket: WebSocket, ip: str, send_lock: asyncio.Lock):
    """Traceroute를 수행하고 홉 정보를 전송한 후 각 홉에 대해 병렬 Ping 수행"""
    if not TRACERT_CMD:
        async with send_lock:
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
        async with send_lock:
            await websocket.send_json({"type": "tracert", "hops": [{"hop": 1, "ip": "Error", "ms": 0, "status": "traceroute command not found"}]})
        return
    except Exception as e:
        print(f"Error starting tracert subprocess for {ip}: {e}")
        async with send_lock:
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
            
            async with send_lock:
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
                
                async with send_lock:
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
    print(f"[WS] WebSocket connection attempt from: {websocket.client.host} for IP: {ip}")
    await websocket.accept()
    print(f"[WS] WebSocket connection accepted for IP: {ip}")
    
    send_lock = asyncio.Lock()
    ping_task = asyncio.create_task(ping_loop(websocket, ip, send_lock))
    tracert_task = asyncio.create_task(tracert_loop(websocket, ip, send_lock))
    
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
