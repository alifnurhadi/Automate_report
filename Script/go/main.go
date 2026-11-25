


# fetch

func fetchJira () {

}


package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type JiraIssue struct {
	ID     string                     `json:"id"`
	Key    string                     `json:"key"`
	Fields map[string]json.RawMessage `json:"fields"`
}

type SearchResponse struct {
	StartAt    int         `json:"startAt"`
	MaxResults int         `json:"maxResults"`
	Total      int         `json:"total"`
	Issues     []JiraIssue `json:"issues"`
}

type SearchRequest struct {
	JQL        string   `json:"jql"`
	StartAt    int      `json:"startAt"`
	MaxResults int      `json:"maxResults"`
	Fields     []string `json:"fields"`
}

type JiraClient struct {
	BaseURL  string
	PAT      string
	Username string
	Password string
	HTTP     *http.Client
}

// Fetch one page from Jira.
func (c *JiraClient) fetchPage(
	ctx context.Context,
	jql string,
	fields []string,
	startAt int,
	pageSize int,
) (SearchResponse, error) {

	var result SearchResponse

	endpoint := strings.TrimRight(c.BaseURL, "/") +
		"/rest/api/2/search"

	payload := SearchRequest{
		JQL:        jql,
		StartAt:    startAt,
		MaxResults: pageSize,
		Fields:     fields,
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return result, err
	}

	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		endpoint,
		bytes.NewReader(body),
	)
	if err != nil {
		return result, err
	}

	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")

	if c.PAT != "" {
		req.Header.Set("Authorization", "Bearer "+c.PAT)
	} else {
		req.SetBasicAuth(c.Username, c.Password)
	}

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return result, err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		errBody, _ := io.ReadAll(
			io.LimitReader(resp.Body, 1<<20),
		)

		return result, fmt.Errorf(
			"HTTP %s: %s",
			resp.Status,
			string(errBody),
		)
	}

	err = json.NewDecoder(resp.Body).Decode(&result)
	if err != nil {
		return result, err
	}

	return result, nil
}

type PageResult struct {
	StartAt int
	Issues  []JiraIssue
}

// Fetch Jira issues using concurrent pagination.
func (c *JiraClient) FetchIssuesConcurrent(
	ctx context.Context,
	jql string,
	fields []string,
	maxWorkers int,
) ([]JiraIssue, error) {

	const pageSize = 100

	// First request determines the total result count
	// and the actual pagination size.
	firstPage, err := c.fetchPage(
		ctx,
		jql,
		fields,
		0,
		pageSize,
	)
	if err != nil {
		return nil, fmt.Errorf("initial Jira request: %w", err)
	}

	allIssues := make([]JiraIssue, 0, firstPage.Total)
	allIssues = append(allIssues, firstPage.Issues...)

	fmt.Printf(
		"Initial page: %d / %d\n",
		len(allIssues),
		firstPage.Total,
	)

	if firstPage.Total <= len(firstPage.Issues) {
		return allIssues, nil
	}

	// Jira may enforce a smaller page size than requested.
	actualPageSize := firstPage.MaxResults
	if actualPageSize <= 0 {
		actualPageSize = pageSize
	}

	// Generate remaining page offsets.
	var offsets []int

	for offset := actualPageSize; offset < firstPage.Total; offset += actualPageSize {
		offsets = append(offsets, offset)
	}

	if maxWorkers < 1 {
		maxWorkers = 1
	}

	if maxWorkers > len(offsets) {
		maxWorkers = len(offsets)
	}

	// Context cancellation allows workers to stop
	// when one request fails.
	pageCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	jobs := make(chan int, len(offsets))
	results := make(chan PageResult, len(offsets))
	errCh := make(chan error, 1)

	for _, offset := range offsets {
		jobs <- offset
	}
	close(jobs)

	var wg sync.WaitGroup

	// Start bounded worker pool.
	for workerID := 1; workerID <= maxWorkers; workerID++ {

		wg.Add(1)

		go func(id int) {
			defer wg.Done()

			for offset := range jobs {

				if pageCtx.Err() != nil {
					return
				}

				page, err := c.fetchPage(
					pageCtx,
					jql,
					fields,
					offset,
					actualPageSize,
				)

				if err != nil {

					select {
					case errCh <- fmt.Errorf(
						"worker %d, offset %d: %w",
						id,
						offset,
						err,
					):
					default:
					}

					cancel()
					return
				}

				results <- PageResult{
					StartAt: offset,
					Issues:  page.Issues,
				}

				fmt.Printf(
					"Worker %d fetched offset %d (%d issues)\n",
					id,
					offset,
					len(page.Issues),
				)
			}
		}(workerID)
	}

	// Close results after every worker finishes.
	go func() {
		wg.Wait()
		close(results)
	}()

	// Store results in their corresponding page positions.
	pages := make([][]JiraIssue, len(offsets))

	for result := range results {

		pageIndex := result.StartAt/actualPageSize - 1

		if pageIndex >= 0 && pageIndex < len(pages) {
			pages[pageIndex] = result.Issues
		}
	}

	select {
	case err := <-errCh:
		return nil, err
	default:
	}

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	// Merge pages in the original pagination order.
	for _, page := range pages {
		allIssues = append(allIssues, page...)
	}

	fmt.Printf(
		"Completed: %d issues retrieved\n",
		len(allIssues),
	)

	return allIssues, nil
}

func main() {

	ctx, cancel := context.WithTimeout(
		context.Background(),
		5*time.Minute,
	)
	defer cancel()

	client := &JiraClient{
		BaseURL:  os.Getenv("JIRA_BASE_URL"),
		PAT:      os.Getenv("JIRA_PAT"),
		Username: os.Getenv("JIRA_USER"),
		Password: os.Getenv("JIRA_TOKEN"),
		HTTP: &http.Client{
			Timeout: 60 * time.Second,
		},
	}

	jql := `
		project in (ERA25, ERA26)
		AND updated >= -30d
		ORDER BY key ASC
	`

	fields := []string{
		"summary",
		"status",
		"assignee",
		"created",
		"updated",
		"customfield_23257",
	}

	issues, err := client.FetchIssuesConcurrent(
		ctx,
		jql,
		fields,
		4, // Maximum concurrent workers
	)

	if err != nil {
		fmt.Println("Fetch error:", err)
		return
	}

	fmt.Println("Total issues:", len(issues))

	// Process retrieved tickets.
	for _, issue := range issues {

		var summary string

		_ = json.Unmarshal(
			issue.Fields["summary"],
			&summary,
		)

		fmt.Printf("%s | %s\n", issue.Key, summary)
	}
}
