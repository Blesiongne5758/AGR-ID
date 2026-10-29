package auction

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/gorilla/websocket"
)

const (
	writeWait      = 10 * time.Second
	pongWait       = 60 * time.Second
	pingPeriod     = (pongWait * 9) / 10
	maxMessageSize = 4096
)

var Upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		// Izinkan koneksi dari frontend aplikasi AGR.ID
		return true
	},
}

// Client mewakili satu koneksi WebSocket pengguna
type Client struct {
	Hub       *Hub
	Room      *Room
	Conn      *websocket.Conn
	Send      chan []byte
	EventID   int
	BuyerID   int
	BuyerName string
}

func (c *Client) ReadPump() {
	defer func() {
		c.Hub.Unregister <- c
		c.Conn.Close()
	}()

	c.Conn.SetReadLimit(maxMessageSize)
	c.Conn.SetReadDeadline(time.Now().Add(pongWait))
	c.Conn.SetPongHandler(func(string) error {
		c.Conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})

	for {
		_, message, err := c.Conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Printf("WebSocket error (Event %d, User %d): %v", c.EventID, c.BuyerID, err)
			}
			break
		}

		var wsMsg WSMessage
		if err := json.Unmarshal(message, &wsMsg); err != nil {
			c.SendError("Format pesan tidak valid")
			continue
		}

		switch wsMsg.Type {
		case "PLACE_BID":
			payloadBytes, err := json.Marshal(wsMsg.Payload)
			if err != nil {
				c.SendError("Data penawaran tidak valid")
				continue
			}

			var req BidRequest
			if err := json.Unmarshal(payloadBytes, &req); err != nil {
				c.SendError("Data penawaran tidak sesuai")
				continue
			}

			req.EventID = c.EventID
			req.BuyerID = c.BuyerID
			req.BuyerName = c.BuyerName
			req.Client = c

			if req.Nominal <= 0 {
				c.SendError("Nominal penawaran harus lebih besar dari 0")
				continue
			}

			// Masukkan penawaran ke antrian room (anti race condition FIFO)
			c.Room.BidsChan <- req

		case "PING":
			c.SendMessage("PONG", map[string]string{"reply": "pong"})
		}
	}
}

func (c *Client) WritePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.Conn.Close()
	}()

	for {
		select {
		case message, ok := <-c.Send:
			c.Conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				c.Conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			w, err := c.Conn.NextWriter(websocket.TextMessage)
			if err != nil {
				return
			}
			w.Write(message)

			// Drain pesan yang masih antre di buffer
			n := len(c.Send)
			for i := 0; i < n; i++ {
				w.Write([]byte{'\n'})
				w.Write(<-c.Send)
			}

			if err := w.Close(); err != nil {
				return
			}

		case <-ticker.C:
			c.Conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.Conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

func (c *Client) SendMessage(msgType string, payload interface{}) {
	data, err := json.Marshal(WSMessage{
		Type:    msgType,
		Payload: payload,
	})
	if err == nil {
		select {
		case c.Send <- data:
		default:
		}
	}
}

func (c *Client) SendError(errMsg string) {
	data, err := json.Marshal(WSMessage{
		Type:  "BID_ERROR",
		Error: errMsg,
	})
	if err == nil {
		select {
		case c.Send <- data:
		default:
		}
	}
}
