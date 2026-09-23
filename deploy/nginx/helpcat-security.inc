# help-cat 的安全响应头。
#
# 为什么要做成单独一个文件：nginx 的 add_header **只在子级自己没有任何 add_header 时**
# 才继承父级。我们的 location 里普遍写了 Cache-Control，那些地方一写就丢掉了父级的
# 安全头，所以必须逐个 include 这个片段。
#
# 用法：install -m 644 deploy/nginx/helpcat-security.inc /etc/nginx/helpcat-security.inc
#       然后在自己写了 add_header 的 location 里写 include /etc/nginx/helpcat-security.inc;
#
# CSP 的口径（按当前前端实际用到的能力定，改前端时要一起看）：
#   script-src 'self'       —— 三个页面都没有内联脚本、没有内联事件处理器、没有 eval
#   style-src 'unsafe-inline' —— app/rescue/index.html 里有一个内联 <style> 块
#   img-src blob:           —— 建档/打卡选择照片时用 URL.createObjectURL 做预览
#   connect-src 'self'      —— 只请求本站 API
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(self), camera=(), microphone=()" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'" always;
