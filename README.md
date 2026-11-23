# Permission Test API

API REST công khai (FastAPI trên Vercel + Neon Postgres) làm mục tiêu thử nghiệm cho AI agent
trong **Copilot Studio** tự động cấp quyền 2 tầng:

1. **Quyền hệ thống** (tầng 1): admin cấp → user *nhìn thấy* miniapp.
2. **Thành viên miniapp** (tầng 2): admin thêm user vào miniapp → user *dùng được* miniapp.
   Phải có tầng 1 trước, nếu không API trả `409 SYSTEM_ACCESS_REQUIRED`.

Base URL: `https://permission-test-api-jvd4.vercel.app`.

## Giao diện demo

- `/`: màn hình thao tác bằng tay, không cần agent. Thanh trên chuyển nhanh giữa **Admin**, **user1**, **user2**.
  - Admin: bảng người dùng × miniapp, mỗi ô có công tắc *Quyền hệ thống* (tầng 1) và *Thành viên* (tầng 2),
    nút *Reset dữ liệu*. Admin key nhập một lần, trình duyệt ghi nhớ (*Đổi admin key* để nhập lại).
  - user1 / user2: các miniapp đang nhìn thấy, nút *Mở miniapp* khi đã là thành viên.
  - Tự cập nhật mỗi 3 giây; ô nào vừa đổi do agent (hoặc nơi khác) sẽ được tô sáng.
- `/status`: bảng trạng thái quyền chỉ đọc, không cần key.

## API key (header `X-API-Key`)

| Tài khoản | Vai trò | Key mặc định |
|---|---|---|
| `admin` | admin | biến môi trường `ADMIN_API_KEY` (mặc định `admin-key-123`, **hãy đổi khi deploy**) |
| `user1` | user | `user1-key-123` |
| `user2` | user | `user2-key-123` |

Miniapp: `leave` (Nghỉ phép), `expense` (Chi phí), `inventory` (Kho).

## Luồng kiểm thử

```bash
B=https://permission-test-api-jvd4.vercel.app; A="X-API-Key: <admin key>"; U="X-API-Key: user1-key-123"
curl -s -X POST $B/admin/system-access -H "$A" -H "Content-Type: application/json" -d '{"username":"user1","miniapp_id":"leave"}'
curl -s $B/me/miniapps -H "$U"                  # leave, can_use=false
curl -s -X POST $B/admin/miniapps/leave/members -H "$A" -H "Content-Type: application/json" -d '{"username":"user1"}'
curl -s -X POST $B/miniapps/leave/use -H "$U"   # 200
curl -s "$B/admin/check?username=user1&miniapp_id=leave" -H "$A"
curl -s -X POST $B/admin/reset -H "$A"          # về trạng thái ban đầu
```

Lỗi luôn là JSON `{"detail": "...", "code": "..."}`. `/admin/check` luôn trả 200.

## Deploy lên Vercel

1. `npx vercel login`, rồi `npx vercel link --yes`.
2. Vercel Dashboard → Storage → thêm **Neon Postgres**, kết nối với project (môi trường Production).
   Kiểm tra: `npx vercel env ls` có `DATABASE_URL`.
3. Thêm biến môi trường Production:
   - `ADMIN_API_KEY` = một chuỗi bí mật (key mặc định đã công khai trong repo này).
   - `PUBLIC_HOST` = `permission-test-api-jvd4.vercel.app` (để `host` trong swagger luôn là domain production).
4. `npx vercel --prod --yes`.
5. Kiểm tra **không dùng cookie**: `curl -s https://permission-test-api-jvd4.vercel.app/health` phải trả
   `{"status":"ok"}`. Nếu nhận về trang HTML đăng nhập Vercel → tắt *Deployment Protection* cho
   Production (Settings → Deployment Protection).

## Import vào Copilot Studio

Dùng URL `https://permission-test-api-jvd4.vercel.app/swagger.json` (OpenAPI 2.0). Lấy URL từ domain production,
không lấy URL của từng deployment (những URL đó bị Deployment Protection chặn).

- Copilot Studio → agent → **Tools → Add a tool → REST API** (hoặc tạo *custom connector* trong
  Power Apps → *Import an OpenAPI from URL*).
- Mỗi thao tác có tham số header `X-API-Key`: thao tác `/admin/...` dùng admin key, thao tác của
  user (`ListMyMiniapps`, `UseMiniapp`, `GetMe`) dùng key của user đó.

## Chạy local

```bash
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -q                     # SQLite, không cần Postgres
node --test "tests/*.test.cjs"                           # logic của giao diện (Node 18+)
.venv/Scripts/python -m uvicorn app:app --reload      # http://127.0.0.1:8000
```

Không có `DATABASE_URL`/`POSTGRES_URL` thì dùng SQLite `./local.db`.
