# Hệ thống đánh giá giả lập (Đánh giá: KPI, thử việc, HĐ, 360)

Phần này giả lập hệ thống đánh giá để test agent xử lý nhóm ticket **Đánh giá** (672 ticket, 14,8% tổng ticket ILVG).
Nó dùng chung API, admin key, người dùng mẫu và nút reset với phần quyền miniapp.

**Không gồm** *Phân quyền quản lý đánh giá* (99 ticket). Phần đó do agent riêng làm trực tiếp trên QTNS UAT.

- Thao tác bằng tay như người xử lý ngoài đời: màn hình **Đánh giá** ở `/?as=admin&section=reviews` (tab *Phiếu đánh giá* và *Kỳ đánh giá*, nhật ký bên phải). Màn hình này không có ô ticket, giống hệ thống thật.
- Trang xem nhanh, chỉ đọc, không cần key, tự tải lại mỗi 10 giây: `/reviews`. Trang có kỳ, phiếu, mục tiêu, người đánh giá và nhật ký.
- API: `/admin/reviews/...`, header `X-API-Key` = admin key. Có 14 thao tác, xem mục 4.
- `POST /admin/reset` khôi phục cả dữ liệu đánh giá, đồng thời xoá kết quả HQCV và nhật ký.

## 1. Nhóm ticket được giả lập

| Nhóm ticket (số ticket) | Ticket đại diện | Thao tác API |
|---|---|---|
| Tạo / mở lại / gia hạn kỳ (188) | "Hỗ trợ gia hạn thêm thời hạn Kỳ đánh giá", "Mở lại kỳ đánh giá quý 2.2026" | `ExtendReviewPeriod`, `ReopenReviewPeriod`, `CreateReviewPeriod`, mở riêng cho 1 người: `ReopenReviewForm` + hạn riêng, `ExtendReviewForm` |
| KPI / mục tiêu: xoá, sửa, phê duyệt (93) | "Hỗ trợ xóa tiêu chí do NLĐ tạo sai", "Hỗ trợ mở hệ thống đánh giá KPI" | `DeleteReviewGoal`, `UpdateReviewGoal`, `ReopenReviewForm` |
| Thử việc / hết hạn hợp đồng (91) | "Cập nhật email đánh giá HĐ của nhân viên", "Xóa các tiêu chí đánh giá hợp đồng sai" | `UpdateReviewEvaluator`, `DeleteReviewGoal`, `ExtendReviewForm` |
| Đánh giá 360 (47) | "Yêu cầu gia hạn biểu mẫu đánh giá 360 - VinFast", "Hỗ trợ cập nhật thông tin người đánh giá 360" | `ExtendReviewPeriod` (kỳ 360), `UpdateReviewEvaluator` + `old_email` |
| Upload kết quả HQCV (17) | | `ImportReviewResults` |

## 2. Dữ liệu mẫu

Nhân viên là các user sẵn có: `user1` (Phòng Đào tạo), `user2` (Phòng Kinh doanh) và `user3` (**đã nghỉ việc**).

**Kỳ đánh giá**

| Kỳ | Trạng thái | Hạn | Dùng để test |
|---|---|---|---|
| `VINFAST-Q3-2026` | Đã đóng | 15/10/2026 | Upload kết quả HQCV |
| `VINFAST-Q4-2026` | Đang mở | 30/11/2026 (gia hạn tối đa đến 30/12) | Gia hạn kỳ |
| `VINFAST-360-2026` | Đang mở | 28/11/2026 | Gia hạn 360 |
| `VINHOMES-Q1-2026` | **Đã chốt kết quả** | 15/04/2026 | Mọi thay đổi đều bị từ chối |
| `VINHOMES-Q2-2026` | Đã đóng | 15/07/2026 | Mở lại kỳ quý 2.2026 |
| `VINHOMES-T11-2026` | Đang mở | 05/12/2026 | Mở lại phiếu đã nộp |
| (chưa có) `VINHOMES-T12-2026` | | | Tạo kỳ mới |

**Phiếu đánh giá**

| Phiếu | Nhân viên | Loại / kỳ | Trạng thái | Điểm cần chú ý |
|---|---|---|---|---|
| `RF-1001` | user1 | KPI `VINFAST-Q4-2026` | Đang nhập | `G-1001-3` là mục tiêu tạo trùng |
| `RF-1002` | user2 | KPI `VINFAST-Q4-2026` | **Đã phê duyệt** | `G-1002-3` nhập sai đơn vị. Phải mở lại phiếu rồi mới xoá được |
| `RF-1003` | user1 | 360 `VINFAST-360-2026` | Đang nhập | 3 người đánh giá, `nguyen.van.a@demo.local` cần thay |
| `RF-1004` | user2 | Thử việc, hạn 30/11 | Đang nhập | Người đánh giá cũ `pham.van.cu@demo.local` đã điều chuyển |
| `RF-1005` | user1 | Hết hạn HĐ, hạn 10/12 | Đã nộp | `G-1005-3`, `G-1005-4` là tiêu chí sai vị trí |
| `RF-1006` | user3 | KPI `VINFAST-Q4-2026` | Đang nhập | Nhân viên đã nghỉ việc |
| `RF-1007` | user2 | KPI `VINHOMES-Q1-2026` | Đã phê duyệt | Kỳ đã chốt |
| `RF-1008` | user2 | KPI `VINHOMES-Q2-2026` | Đang nhập | Kỳ đã đóng, nhân viên chưa nộp |
| `RF-1009` | user1 | KPI `VINHOMES-T11-2026` | Đã nộp | Cần mở lại để sửa |

## 3. Luật (API kiểm tra và chặn, agent chỉ đọc kết quả)

- **Mọi thao tác ghi của agent phải có số ticket SDP** (`#54` hoặc `54`). Thiếu thì trả `422 TICKET_REQUIRED`. Thao tác bằng tay trên màn hình (header `X-Client: console`) không cần ticket.
- Mỗi thay đổi được ghi vào nhật ký (`ListReviewLog`) kèm `ticket` và `actor`: `agent`, hoặc `console` khi làm bằng tay.
- Thao tác ghi thành công trả `200`, kèm `result` = `DONE` hoặc `NO_CHANGE` và `message` (1 câu tiếng Việt).
  Vi phạm luật trả lỗi 4xx `{"detail", "code"}`. `detail` nói cách làm đúng, ví dụ "Mở lại phiếu (ReopenReviewForm) trước…".
- **Kỳ**:
  - Gia hạn: kỳ phải đang mở. Hạn mới phải sau hạn hiện tại và không quá **30 ngày** so với hạn gốc (`max_deadline`).
  - Mở lại: chỉ kỳ đã đóng, hạn mới phải sau hạn cũ.
  - Kỳ **đã chốt** thì không đổi được gì.
  - Tạo kỳ trùng id trả `409 PERIOD_EXISTS`.
- **Phiếu**:
  - Mở lại: phiếu về *Đang nhập*. Nếu kỳ đã đóng thì bắt buộc có **hạn riêng**, tức mở lại cho riêng người đó.
  - Gia hạn: không áp dụng cho phiếu đã phê duyệt. Phiếu thuộc kỳ đã đóng thì dùng mở lại kèm hạn riêng.
- **Mục tiêu / tiêu chí**:
  - Phiếu **đã phê duyệt** thì không xoá, không sửa được (`409 FORM_APPROVED`). Phải mở lại phiếu trước.
  - Sau khi xoá hoặc sửa, nếu tổng trọng số khác 100% thì `message` sẽ nhắc.
- **Người đánh giá**:
  - Phiếu có nhiều người đánh giá (360) phải truyền `old_email`.
  - Nhân viên không tự đánh giá mình được. Người đã nghỉ việc không làm người đánh giá được. Không thêm trùng người.
- **Nhân viên đã nghỉ việc**: mọi thay đổi trên phiếu của họ trả `409 EMPLOYEE_RESIGNED`.
- **Kết quả HQCV**: chỉ tải vào kỳ đã đóng. Tải theo kiểu **tất cả hoặc không**: có 1 dòng sai thì không dòng nào được ghi, `detail` liệt kê từng dòng sai.

## 4. Thao tác

| operationId | Method / path | Việc |
|---|---|---|
| `ListReviewPeriods` | `GET /admin/reviews/periods?company=&status=` | Danh sách kỳ |
| `GetReviewPeriod` | `GET /admin/reviews/periods/{period_id}` | Một kỳ |
| `CreateReviewPeriod` | `POST /admin/reviews/periods` | Tạo kỳ |
| `ReopenReviewPeriod` | `POST /admin/reviews/periods/{period_id}/reopen` | Mở lại kỳ đã đóng cho mọi người |
| `ExtendReviewPeriod` | `POST /admin/reviews/periods/{period_id}/extend` | Gia hạn kỳ đang mở |
| `ImportReviewResults` | `POST /admin/reviews/periods/{period_id}/results` | Upload kết quả HQCV |
| `FindReviewForms` | `GET /admin/reviews/forms?email=&username=&period_id=&kind=` | Tìm phiếu của nhân viên (gọi đầu tiên) |
| `GetReviewForm` | `GET /admin/reviews/forms/{form_id}` | Một phiếu (kiểm tra lại sau khi sửa) |
| `ReopenReviewForm` | `POST /admin/reviews/forms/{form_id}/reopen` | Mở lại phiếu, có thể kèm hạn riêng |
| `ExtendReviewForm` | `POST /admin/reviews/forms/{form_id}/extend` | Gia hạn riêng một phiếu |
| `UpdateReviewEvaluator` | `PUT /admin/reviews/forms/{form_id}/evaluator` | Đổi người đánh giá |
| `UpdateReviewGoal` | `PUT /admin/reviews/goals/{goal_id}` | Sửa mục tiêu / tiêu chí |
| `DeleteReviewGoal` | `DELETE /admin/reviews/goals/{goal_id}?ticket=` | Xoá mục tiêu / tiêu chí |
| `ListReviewLog` | `GET /admin/reviews/log?ticket=&target=` | Nhật ký thay đổi |

## 5. Kịch bản test (ticket → kết quả đúng)

Tạo các ticket này trên SDP, requester là email của nhân viên trong bảng ở mục 2.

| # | Ticket | Kết quả đúng |
|---|---|---|
| 1 | user1: "Hỗ trợ gia hạn kỳ đánh giá KPI quý 4 VinFast đến 10/12" | `ExtendReviewPeriod` `VINFAST-Q4-2026` → DONE |
| 2 | "Gia hạn kỳ KPI quý 4 VinFast đến 31/12" | Từ chối `EXTENSION_TOO_LONG`: tối đa đến 30/12/2026 |
| 3 | "Mở lại kỳ đánh giá quý 2.2026 Vinhomes đến 05/12" | `ReopenReviewPeriod` `VINHOMES-Q2-2026` → DONE |
| 4 | user2: "Mở lại kỳ đánh giá quý 2.2026 cho em, em chưa kịp nộp" | `ReopenReviewForm` `RF-1008` kèm hạn riêng → DONE. Kỳ vẫn đóng với người khác |
| 5 | "Mở lại kỳ đánh giá quý 1.2026 Vinhomes" | Từ chối `PERIOD_LOCKED`: kỳ đã chốt kết quả |
| 6 | "Tạo kỳ đánh giá KPI tháng 12/2026 cho Vinhomes" | `CreateReviewPeriod` → `VINHOMES-T12-2026` |
| 7 | user1: "Hỗ trợ xóa tiêu chí do NLĐ tạo sai" (mục tiêu tạo trùng) | `DeleteReviewGoal` `G-1001-3` → DONE, nhắc tổng trọng số còn 80% |
| 8 | user2: "Xóa mục tiêu doanh số quý 4 nhập sai đơn vị" | Phiếu đã phê duyệt: **một kế hoạch, một lần xác nhận** gồm `ReopenReviewForm` `RF-1002` → `DeleteReviewGoal` `G-1002-3` |
| 9 | user1: "Hỗ trợ mở hệ thống đánh giá KPI tháng 11 để sửa" | `ReopenReviewForm` `RF-1009` → về *Đang nhập* |
| 10 | user2: "Cập nhật email đánh giá thử việc sang truongphong.kinhdoanh@demo.local" | `UpdateReviewEvaluator` `RF-1004` → DONE |
| 11 | user1: "Xóa các tiêu chí đánh giá hợp đồng sai" | `DeleteReviewGoal` `G-1005-3`, `G-1005-4` → DONE, nhắc tổng trọng số 70% |
| 12 | "Yêu cầu gia hạn biểu mẫu đánh giá 360 - VinFast đến 05/12" | `ExtendReviewPeriod` `VINFAST-360-2026` → DONE |
| 13 | user1: "Cập nhật người đánh giá 360: thay nguyen.van.a bằng tran.thi.b@demo.local" | `UpdateReviewEvaluator` `RF-1003` với `old_email` → DONE |
| 14 | user3: "Gia hạn phiếu KPI quý 4" | Từ chối `EMPLOYEE_RESIGNED`: nhân viên đã nghỉ việc |
| 15 | "Upload kết quả HQCV quý 3 VinFast" (bảng email, điểm, xếp loại) | `ImportReviewResults` `VINFAST-Q3-2026` → DONE |
| 16 | user2: "Đổi người đánh giá thử việc thành user2@demo.local" | Từ chối `SELF_EVALUATOR` |

```bash
B=https://permission-test-api-jvd4.vercel.app; A="X-API-Key: <admin key>"; J="Content-Type: application/json"
curl -s "$B/admin/reviews/forms?email=user2@demo.local&kind=KPI" -H "$A"
curl -s -X POST "$B/admin/reviews/periods/VINFAST-Q4-2026/extend" -H "$A" -H "$J" -d '{"deadline":"2026-12-10","ticket":"#54"}'
curl -s -X DELETE "$B/admin/reviews/goals/G-1002-3?ticket=%2355" -H "$A"     # 409 FORM_APPROVED
curl -s -X POST "$B/admin/reviews/forms/RF-1002/reopen" -H "$A" -H "$J" -d '{"ticket":"#55"}'
curl -s -X DELETE "$B/admin/reviews/goals/G-1002-3?ticket=%2355" -H "$A"     # DONE
curl -s "$B/admin/reviews/log?ticket=55" -H "$A"
```
