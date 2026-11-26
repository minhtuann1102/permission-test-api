# Permission Test API

API REST công khai (FastAPI trên Vercel + Neon Postgres) làm mục tiêu thử nghiệm cho AI agent
trong **Copilot Studio** tự động cấp quyền 2 tầng:

1. **Quyền hệ thống** (tầng 1): admin cấp → user *nhìn thấy* miniapp.
2. **Thành viên miniapp** (tầng 2): admin thêm user vào miniapp → user *dùng được* miniapp.
   Phải có tầng 1 trước, nếu không API trả `409 SYSTEM_ACCESS_REQUIRED`.

Base URL: `https://permission-test-api-jvd4.vercel.app`.

## Hệ thống đánh giá giả lập (Đánh giá: KPI, thử việc, HĐ, 360)

Cùng API này còn giả lập **hệ thống đánh giá**, dùng để test agent xử lý nhóm ticket Đánh giá:

- gia hạn, mở lại, tạo kỳ;
- mở lại phiếu;
- xoá, sửa mục tiêu và tiêu chí;
- đổi người đánh giá thử việc, hợp đồng, 360;
- upload kết quả HQCV.

Phân quyền quản lý đánh giá không nằm ở đây. API có 14 thao tác `/admin/reviews/...` (admin key). Mọi thao tác ghi của agent đều phải có số ticket SDP. Màn hình thao tác tay ở `/` không có ô ticket, giống hệ thống thật. Mọi thay đổi được ghi nhật ký kèm người làm (*Agent* hoặc *Thao tác tay*) và ticket nếu có.
Trang chỉ đọc là `/reviews`. Dữ liệu mẫu, luật và kịch bản test có trong [docs/reviews.md](docs/reviews.md).

## Giao diện demo

- `/`: màn hình thao tác bằng tay như người xử lý ngoài đời, không cần agent. Thanh trên chuyển nhanh giữa
  **Admin**, **user1**, **user2**, **user3**; với Admin có thêm hai mục **Phân quyền miniapp** và **Đánh giá**
  (`/?as=admin&section=permissions|reviews`).
  - *Phân quyền miniapp*: chọn người dùng → xem quyền đang có (bấm ✕ để thu hồi: chỉ quyền dùng, hoặc thu hồi hết)
    → chọn nhiều quyền trong dropdown (mỗi miniapp *Xem* hoặc *Sử dụng*, LMS *Học viên* / *Giảng viên*) →
    **Cấp N quyền** → hộp xác nhận liệt kê trước → sau và kết quả kiểm tra điều kiện → kết quả từng quyền.
    Chọn *Sử dụng* thì tự cấp luôn quyền hệ thống; một quyền bị từ chối không làm hỏng các quyền khác.
  - *Đánh giá*: tab *Phiếu đánh giá* (chọn nhân viên → phiếu của họ → mở lại, gia hạn, đổi người đánh giá,
    sửa / xoá mục tiêu; phiếu đã phê duyệt thì một lần xác nhận *Mở lại phiếu rồi …*) và tab *Kỳ đánh giá*
    (gia hạn, mở lại, tạo kỳ, dán bảng kết quả HQCV). Thao tác bị luật chặn thì nút mờ kèm lý do.
  - **Nhật ký thay đổi** luôn ở bên phải, tự cập nhật mỗi 3 giây: mỗi thay đổi một dòng, ghi *Thao tác tay*
    (màn hình này, gửi header `X-Client: console`) hoặc *Agent* (mọi lời gọi khác), dòng mới được tô sáng.
    Thao tác bị từ chối không ghi nhật ký, chỉ báo lý do trên màn hình.
  - Admin key nhập một lần, trình duyệt ghi nhớ (*Đổi admin key* để nhập lại). *Reset dữ liệu* xoá cả nhật ký.
  - user1 / user2 / user3: các miniapp đang nhìn thấy, nút *Mở miniapp* khi đã là thành viên.
- `/status`: bảng tổng quan trạng thái quyền (người dùng × miniapp), chỉ đọc, không cần key.
- `/reviews`: kỳ, phiếu, mục tiêu, người đánh giá và nhật ký của hệ thống đánh giá giả lập. Chỉ đọc, không cần key.
- `/org`: sơ đồ tổ chức giả lập dạng cây (bậc, chức danh, đơn vị, người đã nghỉ việc) dùng cho thẩm định phê duyệt.
  Chỉ đọc, không cần key. Bản JSON: `GET /admin/org/people` (admin key).

## API key (header `X-API-Key`)

| Tài khoản | Vai trò | Key mặc định |
|---|---|---|
| `admin` | admin | biến môi trường `ADMIN_API_KEY` (mặc định `admin-key-123`, **hãy đổi khi deploy**) |
| `user1` | user | `user1-key-123` |
| `user2` | user | `user2-key-123` |
| `user3` | user | `user3-key-123` |

## Người dùng mẫu và điều kiện cấp quyền

Dữ liệu tổ chức giả lập, dùng để API **tự kiểm tra và chặn** người không đủ điều kiện. Agent chỉ đọc kết quả.

| username | email | Đơn vị | Chức danh | Quản lý trực tiếp | Trạng thái |
|---|---|---|---|---|---|
| `admin` | `admin@demo.local` | Phòng CNTT | Quản trị hệ thống | (trống) | ACTIVE |
| `user1` | `user1@demo.local` | Phòng Đào tạo (L&D) | Chuyên viên đào tạo | `truongphong.daotao@demo.local` | ACTIVE |
| `user2` | `user2@demo.local` | Phòng Kinh doanh | Nhân viên kinh doanh | `truongphong.kinhdoanh@demo.local` | ACTIVE |
| `user3` | `user3@demo.local` | Phòng Kinh doanh | Nhân viên kinh doanh | `truongphong.kinhdoanh@demo.local` | **RESIGNED** |

Luật (bảng `role_rules`, mỗi dòng là một cách đủ điều kiện: đơn vị khớp chính xác **hoặc** chức danh chứa từ khoá, không phân biệt hoa thường):

| Miniapp / vai trò | Ai đủ điều kiện |
|---|---|
| `lms` / `instructor` (Giảng viên) | Phòng Đào tạo (L&D), hoặc chức danh chứa "giảng viên" |
| Mọi cặp khác (`lms` / `learner`, `leave`, `expense`, `inventory`) | Mọi người |
| Mọi thao tác cấp | Không cấp cho người `RESIGNED` (đã nghỉ việc). Thu hồi luôn được phép |

- `GET /admin/eligibility?username=&miniapp_id=&role=&approver_email=` (`CheckEligibility`, admin): **luôn trả 200**
  với `eligible`, `reasons` (câu tiếng Việt), đơn vị, chức danh, trạng thái, `manager_email`.
  Truyền `approver_email` thì có thêm `approver_checked: true` và `approver_ok` (người duyệt có phải quản lý trực tiếp không).
- `GrantSystemAccess` và `AddMiniappMember` (kể cả đổi vai trò) trả `403 NOT_ELIGIBLE` khi không đủ điều kiện,
  `detail` là lý do đầu tiên, và không ghi gì vào database. `RevokeSystemAccess`, `RemoveMiniappMember` không bị chặn.
- `GetMe`, `ListUsers`, `FindUserByEmail` trả thêm `department`, `title`, `manager_email`, `status`.

```bash
B=https://permission-test-api-jvd4.vercel.app; A="X-API-Key: <admin key>"
curl -s "$B/admin/eligibility?username=user1&miniapp_id=lms&role=instructor" -H "$A"   # eligible: true, "Thuộc Phòng Đào tạo (L&D)"
curl -s "$B/admin/eligibility?username=user2&miniapp_id=lms&role=instructor" -H "$A"   # eligible: false
curl -s "$B/admin/eligibility?username=user3&miniapp_id=leave" -H "$A"                 # eligible: false, đã nghỉ việc
curl -s "$B/admin/eligibility?username=user1&miniapp_id=leave&approver_email=ai.do@demo.local" -H "$A"  # approver_ok: false
```

Miniapp: `leave` (Nghỉ phép), `expense` (Chi phí), `inventory` (Kho), `lms` (LMS).

**LMS giả lập** (`lms`) chỉ có trong API này, không kết nối hệ thống LMS nào khác:

- Luôn hiển thị với mọi người, không cần quyền hệ thống (tầng 1). `GrantSystemAccess` trả `already_granted: true`.
- Thành viên có vai trò `learner` (Học viên) hoặc `instructor` (Giảng viên):
  `POST /admin/miniapps/lms/members` body `{"username": "user1", "role": "instructor"}`.
  Bỏ trống `role` thì là `learner`. Gọi lại với vai trò khác thì đổi vai trò. Vai trò sai trả `422 INVALID_ROLE`.
- `CheckAccess`, `ListMyMiniapps` trả thêm `role`; `ListUsers`, `FindUserByEmail` trả thêm `member_roles`.

`/swagger.json` trả header CORS `Access-Control-Allow-Origin: *` để công cụ import chạy trên trình duyệt đọc được spec.
Các endpoint khác, nhất là `/admin`, không có CORS.

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

Lỗi luôn là JSON `{"detail": "...", "code": "..."}`. `/admin/check` và `/admin/eligibility` luôn trả 200.

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

Hướng dẫn đầy đủ (tạo agent, tool, gán key, instructions, kiểm tra, xử lý sự cố):
[docs/copilot-studio-agent-setup.md](docs/copilot-studio-agent-setup.md).

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
