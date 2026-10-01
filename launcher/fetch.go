// 웹 가져오기: 인터넷 검색 결과·웹페이지·공개 시세 API를 대신 받아 준다.
// 공용 인터넷 주소만 허용하고(내부망·이 컴퓨터 주소 차단), 세션 토큰이 있는 요청만 받는다.
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"syscall"
	"time"
)

func isPublicIP(ip net.IP) bool {
	if ip == nil || ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsMulticast() || ip.IsUnspecified() {
		return false
	}
	if v4 := ip.To4(); v4 != nil && (v4[0] == 0 || (v4[0] == 100 && v4[1]&0xc0 == 64)) { // 0.0.0.0/8, CGNAT
		return false
	}
	return true
}

var webClient = &http.Client{
	Timeout: 25 * time.Second,
	Transport: &http.Transport{
		Proxy: nil, // 프록시를 거치면 실제 접속 주소를 검사할 수 없으므로 직접 연결
		DialContext: (&net.Dialer{
			Timeout: 10 * time.Second,
			// 실제로 접속하는 IP를 검사해 내부망 접근(DNS 재바인딩 포함)을 막는다
			Control: func(network, address string, c syscall.RawConn) error {
				if os.Getenv("NURI_ALLOW_PRIVATE") == "1" { // 테스트용
					return nil
				}
				host, _, err := net.SplitHostPort(address)
				if err != nil {
					return err
				}
				if !isPublicIP(net.ParseIP(host)) {
					return errors.New("내부망 주소는 가져올 수 없습니다")
				}
				return nil
			},
		}).DialContext,
		TLSHandshakeTimeout: 10 * time.Second,
	},
	CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if len(via) >= 5 {
			return errors.New("리디렉션이 너무 많습니다")
		}
		return nil
	},
}

func fetchHandler(w http.ResponseWriter, r *http.Request) {
	if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	if r.Header.Get("X-Nuri-Token") != sessionToken {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	raw := r.URL.Query().Get("url")
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		http.Error(w, "http/https 주소만 가져올 수 있습니다", http.StatusBadRequest)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
	defer cancel()
	target := u.String()
	if via := os.Getenv("NURI_FETCH_VIA"); via != "" && os.Getenv("NURI_ALLOW_PRIVATE") == "1" { // 테스트용: 모든 요청을 흉내 서버로
		target = via + "/" + u.Host + u.RequestURI()
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 NuriAI/1.0")
	req.Header.Set("Accept", "text/html,application/json,application/xhtml+xml,*/*;q=0.8")
	req.Header.Set("Accept-Language", "ko-KR,ko;q=0.9,en;q=0.8")
	res, err := webClient.Do(req)
	if err != nil {
		http.Error(w, "가져오기 실패: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer res.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(res.Body, 4<<20))
	ct := res.Header.Get("Content-Type")
	if ct == "" {
		ct = "application/octet-stream"
	}
	w.Header().Set("Content-Type", ct)
	w.Header().Set("X-Final-Url", res.Request.URL.String())
	w.Header().Set("X-Upstream-Status", fmt.Sprint(res.StatusCode))
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(res.StatusCode)
	w.Write(body)
}
