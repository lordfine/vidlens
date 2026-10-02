# 登录态自动化走 hint 协议,不耦合浏览器

真实用户 cookie(抖音/B站登录态)失效时,vidlens 不自动从浏览器读取(不做任何浏览器自动化),而是以 exit 2 退出,并在 error.hint 中写给 agent 的指令:用浏览器自动化(如 CDP)从用户浏览器取 cookie 传给 `--cookie`,或请用户手动提供。匿名 ttwid 的失效则静默自动重注册,不打扰任何人。

理由:自动搬取用户登录态对开源工具是安全上的脏耦合,且 vidlens 的定位是"agent 功能包"——agent 侧本就有 web-access 这类浏览器能力,hint 协议让 agent 闭环执行,工具保持纯净。
