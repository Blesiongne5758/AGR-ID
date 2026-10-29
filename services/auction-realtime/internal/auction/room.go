package auction

import (
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"
)

// Room mengelola satu event lelang dan seluruh peserta yang sedang menonton/menawar
type Room struct {
	EventID        int
	Status         string
	StartingPrice  float64
	CurrentPrice   float64
	HighestBidder  string
	HighestBuyerID int
	MinimumBid     float64

	clients      map[*Client]bool
	clientsMutex sync.RWMutex

	BidsChan chan BidRequest
	history  []BidBroadcast
	mu       sync.Mutex
	stopChan chan struct{}
}

func NewRoom(eventID int, startingPrice float64) *Room {
	r := &Room{
		EventID:       eventID,
		Status:        "berlangsung",
		StartingPrice: startingPrice,
		CurrentPrice:  startingPrice,
		MinimumBid:    startingPrice + 1,
		clients:       make(map[*Client]bool),
		BidsChan:      make(chan BidRequest, 256),
		history:       make([]BidBroadcast, 0),
		stopChan:      make(chan struct{}),
	}
	go r.run()
	return r
}

func (r *Room) run() {
	for {
		select {
		case <-r.stopChan:
			return
		case req := <-r.BidsChan:
			r.processBid(req)
		}
	}
}

func (r *Room) processBid(req BidRequest) {
	r.mu.Lock()
	defer r.mu.Unlock()

	// 1. Validasi: Nominal harus lebih besar dari tawaran tertinggi saat ini
	currentThreshold := r.CurrentPrice
	if r.HighestBuyerID == 0 {
		// Jika belum ada penawar, nominal harus minimal sama dengan atau lebih besar dari harga awal
		currentThreshold = r.StartingPrice - 1
	}

	if req.Nominal <= currentThreshold {
		if req.Client != nil {
			req.Client.SendError(fmt.Sprintf("Tawaran Rp%.0f ditolak. Minimal tawaran saat ini adalah Rp%.0f.", req.Nominal, r.MinimumBid))
		}
		return
	}

	// 2. Update state harga tertinggi room
	r.CurrentPrice = req.Nominal
	r.HighestBidder = req.BuyerName
	r.HighestBuyerID = req.BuyerID
	r.MinimumBid = req.Nominal + 1

	now := time.Now()
	broadcastItem := BidBroadcast{
		ID:        now.UnixNano(),
		EventID:   r.EventID,
		BuyerID:   req.BuyerID,
		BuyerName: req.BuyerName,
		Nominal:   req.Nominal,
		Catatan:   req.Catatan,
		Timestamp: now,
		MinNext:   r.MinimumBid,
	}

	// Simpan ke riwayat lokal room
	r.history = append([]BidBroadcast{broadcastItem}, r.history...)
	if len(r.history) > 50 {
		r.history = r.history[:50]
	}

	log.Printf("[Lelang #%d] Tawaran Baru Diterima: Rp%.0f dari %s (ID %d)", r.EventID, req.Nominal, req.BuyerName, req.BuyerID)

	// Beri feedback sukses ke penawar
	if req.Client != nil {
		req.Client.SendMessage("BID_ACCEPTED", map[string]interface{}{
			"nominal": req.Nominal,
			"message": "Tawaran Anda berhasil dipasang dan menjadi penawar tertinggi!",
		})
	}

	// 3. Broadcast ke SEMUA peserta di room ini
	r.Broadcast("NEW_BID", broadcastItem)
}

// IngestExternalBid menerima pemberitahuan bid dari luar (misal form HTTP Flask / DB)
func (r *Room) IngestExternalBid(buyerID int, buyerName string, amount float64, catatan string) {
	r.BidsChan <- BidRequest{
		EventID:   r.EventID,
		BuyerID:   buyerID,
		BuyerName: buyerName,
		Nominal:   amount,
		Catatan:   catatan,
		Client:    nil,
	}
}

func (r *Room) AddClient(c *Client) {
	r.clientsMutex.Lock()
	r.clients[c] = true
	count := len(r.clients)
	r.clientsMutex.Unlock()

	c.Room = r

	// Kirim state awal lelang saat pengguna baru tersambung
	r.mu.Lock()
	state := RoomState{
		EventID:        r.EventID,
		Status:         r.Status,
		CurrentPrice:   r.CurrentPrice,
		HighestBidder:  r.HighestBidder,
		MinimumBid:     r.MinimumBid,
		TotalBids:      len(r.history),
		ConnectedUsers: count,
		RecentBids:     r.history,
	}
	r.mu.Unlock()

	c.SendMessage("INIT_STATE", state)

	// Broadcast update jumlah penonton online
	r.Broadcast("AUDIENCE_UPDATE", map[string]interface{}{
		"connected_users": count,
	})
}

func (r *Room) RemoveClient(c *Client) {
	r.clientsMutex.Lock()
	delete(r.clients, c)
	count := len(r.clients)
	r.clientsMutex.Unlock()

	r.Broadcast("AUDIENCE_UPDATE", map[string]interface{}{
		"connected_users": count,
	})
}

func (r *Room) Broadcast(msgType string, payload interface{}) {
	data, err := json.Marshal(WSMessage{
		Type:    msgType,
		Payload: payload,
	})
	if err != nil {
		return
	}

	r.clientsMutex.RLock()
	defer r.clientsMutex.RUnlock()

	for client := range r.clients {
		select {
		case client.Send <- data:
		default:
			// Buffer penuh, unregister secara aman
			close(client.Send)
			delete(r.clients, client)
		}
	}
}
