package handlers

import (
	"net"
	"strings"

	"github.com/gin-gonic/gin"
)

// ParseTrustedProxies 把 TRUSTED_PROXIES（逗号分隔的 IP 或 CIDR）解析成网段集合。
// 裸 IP 按 /32（IPv4）或 /128（IPv6）处理。解析不出的条目被丢弃——宁可少信任，不能多信任。
func ParseTrustedProxies(specs []string) []*net.IPNet {
	nets := make([]*net.IPNet, 0, len(specs))
	for _, raw := range specs {
		spec := strings.TrimSpace(raw)
		if spec == "" {
			continue
		}
		var cidr *net.IPNet
		if strings.Contains(spec, "/") {
			_, parsed, err := net.ParseCIDR(spec)
			if err != nil {
				continue
			}
			cidr = parsed
		} else {
			ip := net.ParseIP(spec)
			if ip == nil {
				continue
			}
			if v4 := ip.To4(); v4 != nil {
				cidr = &net.IPNet{IP: v4, Mask: net.CIDRMask(32, 32)}
			} else {
				cidr = &net.IPNet{IP: ip, Mask: net.CIDRMask(128, 128)}
			}
		}
		nets = append(nets, cidr)
	}
	return nets
}

// ClientIP 返回限流计数用的客户端地址（不含端口）。
//
// 只有直连对端本身可信（落在 trusted 内）才采纳 X-Forwarded-For，否则一律用直连地址。
// 这条前置判断是命门：XFF 是客户端可随意伪造的头部，无条件采信的话，攻击者每次请求换一个
// 假 IP 就等于每次一个全新配额桶，限流彻底失效——比「所有人共享一个桶」更糟。
//
// 取法自右向左、跳过可信代理，第一个不可信地址即答案：XFF 是「client, proxy1, proxy2」的
// 追加序，右侧才由自家代理写入，左侧是客户端自带内容，永远不可信。
func ClientIP(c *gin.Context, trusted []*net.IPNet) string {
	peer := parseIPToken(c.Request.RemoteAddr)
	if peer == nil {
		// 对端解析不出（理论不可达）：退回原始串，保证调用方拿到的键非空
		return c.Request.RemoteAddr
	}
	if len(trusted) == 0 || !ipInAny(peer, trusted) {
		return peer.String()
	}
	hops := strings.Split(c.Request.Header.Get("X-Forwarded-For"), ",")
	for i := len(hops) - 1; i >= 0; i-- {
		ip := parseIPToken(hops[i])
		if ip == nil {
			continue
		}
		if !ipInAny(ip, trusted) {
			return ip.String()
		}
	}
	return peer.String()
}

// parseIPToken 解析一个可能是「host:port」「[v6]:port」「v6%zone」「裸 host」的片段。
func parseIPToken(token string) net.IP {
	token = strings.TrimSpace(strings.Trim(token, `"`))
	if token == "" {
		return nil
	}
	if host, _, err := net.SplitHostPort(token); err == nil {
		token = host
	}
	// IPv6 zone（fe80::1%eth0）参与解析会失败，去掉
	if i := strings.IndexByte(token, '%'); i >= 0 {
		token = token[:i]
	}
	return net.ParseIP(strings.Trim(token, "[]"))
}

func ipInAny(ip net.IP, nets []*net.IPNet) bool {
	for _, n := range nets {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}
