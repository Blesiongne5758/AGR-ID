package auction

import "time"

// WSMessage represents the standard envelope for WebSocket communication
type WSMessage struct {
	Type    string      `json:"type"`              // e.g. "INIT_STATE", "PLACE_BID", "NEW_BID", "BID_ERROR", "BID_SUCCESS"
	Payload interface{} `json:"payload,omitempty"` // Data payload
	Error   string      `json:"error,omitempty"`   // Error message if any
}

// BidRequest represents an incoming bid from a client
type BidRequest struct {
	EventID   int     `json:"event_id"`
	BuyerID   int     `json:"buyer_id"`
	BuyerName string  `json:"buyer_name"`
	Nominal   float64 `json:"nominal"`
	Catatan   string  `json:"catatan,omitempty"`
	Client    *Client `json:"-"`
}

// BidBroadcast represents a newly validated bid broadcast to all subscribers
type BidBroadcast struct {
	ID        int64     `json:"id"`
	EventID   int       `json:"event_id"`
	BuyerID   int       `json:"buyer_id"`
	BuyerName string    `json:"buyer_name"`
	Nominal   float64   `json:"nominal"`
	Catatan   string    `json:"catatan,omitempty"`
	Timestamp time.Time `json:"timestamp"`
	MinNext   float64   `json:"min_next"`
}

// RoomState represents the current snapshot of an auction event
type RoomState struct {
	EventID         int            `json:"event_id"`
	Status          string         `json:"status"`
	CurrentPrice    float64        `json:"current_price"`
	HighestBidder   string         `json:"highest_bidder"`
	MinimumBid      float64        `json:"minimum_bid"`
	TotalBids       int            `json:"total_bids"`
	ConnectedUsers  int            `json:"connected_users"`
	RecentBids      []BidBroadcast `json:"recent_bids"`
}
