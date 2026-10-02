# 抖音解析走 iesdouyin 分享页,不走 yt-dlp

yt-dlp 的 DouyinIE 裸调 `aweme/v1/web/aweme/detail/` Web API 且不含任何签名逻辑(源码中无 a_bogus 计算),匿名请求必然被风控拒绝(实测 exit 3)。我们决定主路径改为解析 iesdouyin 移动分享页内嵌的 `_ROUTER_DATA` JSON,配合自动注册的匿名 ttwid cookie 即可稳定获取元信息与播放直链(playwm 替换为 play 得无水印流);yt-dlp 降级为兜底路径。

## Considered Options

- **yt-dlp 直取**:匿名不可用;需用户登录 cookie 才偶尔可行,与"匿名开箱即用"目标冲突。
- **自研 a_bogus 签名**:需执行抖音 webmssdk.js,维护成本高且随版本漂移。
- **iesdouyin 分享页(选定)**:老 webview 页面,无签名要求,ttwid 匿名可得。
